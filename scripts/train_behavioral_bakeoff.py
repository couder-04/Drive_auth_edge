#!/usr/bin/env python3
"""Behavioral bake-off: LSTM vs GRU vs windowed LightGBM → wire best into store.

Trains on Phase-3 synth (or real) CAN/IMU windows under data/<driver>/behavioral/,
compares via leave-one-out AUC + genuine/attack score separation, exports the
winner as ONNX + encrypted profile for BehavioralMonitor.

IMPORTANT: synth CAN is a pipeline stand-in. Re-run this bake-off on real CAN
before treating metrics as production-ready (see TODO.txt).

Usage:
  python scripts/train_behavioral_bakeoff.py \\
    --data data/driver1/behavioral \\
    --store driveauth_store_phase2a \\
    --driver-id driver1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.matchers.behavioral import (  # noqa: E402
    BEHAVIORAL_FEATURE_KEYS,
    WINDOW_STAT_KEYS,
    window_stat_features,
)
from driveauth.template_store import save_embedding  # noqa: E402

EMB_DIM = 32
WINDOW = 50
N_FEAT = len(BEHAVIORAL_FEATURE_KEYS)
SEED = 42


@dataclass
class CandidateResult:
    name: str
    auc: float
    accuracy: float
    genuine_mean: float
    attack_mean: float
    separation: float


def _load_windows(
    data_dir: Path,
    *,
    real_data_dir: Path | None = None,
    real_repeat: int = 3,
) -> tuple[np.ndarray, np.ndarray, list[str], int]:
    """Return X (N, T, F), y (N,), paths, and n_real_windows (pre-repeat)."""
    xs: list[np.ndarray] = []
    ys: list[int] = []
    paths: list[str] = []
    n_real = 0

    def _ingest(root: Path, *, is_real: bool) -> None:
        nonlocal n_real
        for split, label in (("genuine", 1), ("attack", 0)):
            folder = root / split
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("can_*.csv")):
                with path.open(newline="") as f:
                    rows = list(csv.DictReader(f))
                if len(rows) < 5:
                    continue
                mat = np.array(
                    [[float(r[k]) for k in BEHAVIORAL_FEATURE_KEYS] for r in rows],
                    dtype=np.float32,
                )
                if mat.shape[0] > WINDOW:
                    mat = mat[-WINDOW:]
                elif mat.shape[0] < WINDOW:
                    pad = np.repeat(mat[:1], WINDOW - mat.shape[0], axis=0)
                    mat = np.concatenate([pad, mat], axis=0)
                repeats = real_repeat if is_real else 1
                if is_real:
                    n_real += 1
                for _ in range(repeats):
                    xs.append(mat)
                    ys.append(label)
                    paths.append(
                        ("real:" if is_real else "synth:")
                        + str(path.relative_to(root))
                    )

    _ingest(data_dir, is_real=False)
    if real_data_dir is not None and real_data_dir.is_dir():
        # Accept either behavioral/ root or a dump that already has genuine/.
        if (real_data_dir / "genuine").is_dir() or (real_data_dir / "attack").is_dir():
            _ingest(real_data_dir, is_real=True)
        elif (real_data_dir / "behavioral").is_dir():
            _ingest(real_data_dir / "behavioral", is_real=True)
    if not xs:
        raise SystemExit(f"No can_*.csv windows under {data_dir}")
    return np.stack(xs), np.asarray(ys, dtype=np.int64), paths, n_real


def _warn_zero_real_samples(n_real: int) -> None:
    if n_real > 0:
        return
    print(
        "\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        "! WARNING: train_behavioral_bakeoff used ZERO real samples.\n"
        "! Metrics remain synthetic-only — not production-ready.\n"
        "! Collect fleet logs via hardware/can_logger.py and pass\n"
        "! --real-data-dir before trusting bake-off winners.\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n",
        flush=True,
    )


def _fit_norm(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x: (N, T, F) → per-feature mean/std over all timesteps."""
    flat = x.reshape(-1, x.shape[-1])
    mean = flat.mean(axis=0).astype(np.float32)
    std = flat.std(axis=0).astype(np.float32)
    std = np.where(std < 1e-6, 1.0, std)
    return mean, std


def _apply_norm(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return ((x - mean) / std).astype(np.float32)


def _auc_binary(y_true: np.ndarray, scores: np.ndarray) -> float:
    """ROC AUC without sklearn (higher score = genuine)."""
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Mann–Whitney
    correct = 0.0
    for p in pos:
        correct += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return correct / (len(pos) * len(neg))


def _metrics(y: np.ndarray, scores: np.ndarray, name: str) -> CandidateResult:
    auc = _auc_binary(y, scores)
    pred = (scores >= 0.5).astype(int)
    acc = float(np.mean(pred == y))
    g = float(scores[y == 1].mean()) if np.any(y == 1) else float("nan")
    a = float(scores[y == 0].mean()) if np.any(y == 0) else float("nan")
    return CandidateResult(
        name=name,
        auc=float(auc),
        accuracy=acc,
        genuine_mean=g,
        attack_mean=a,
        separation=g - a,
    )


# ── RNN (LSTM / GRU) ─────────────────────────────────────────────────────────

def _stratified_folds(y: np.ndarray, k: int = 5) -> list[np.ndarray]:
    """Return list of boolean test-masks for stratified K-fold."""
    rng = np.random.default_rng(SEED)
    folds = [np.zeros(len(y), dtype=bool) for _ in range(k)]
    for label in (0, 1):
        idx = np.where(y == label)[0]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            folds[j % k][i] = True
    return folds


def _train_rnn_cv(
    name: str,
    x: np.ndarray,
    y: np.ndarray,
    *,
    epochs: int = 25,
    folds: int = 5,
) -> tuple[CandidateResult, object, np.ndarray, np.ndarray, np.ndarray]:
    import torch
    import torch.nn as nn

    torch.set_num_threads(2)

    class EmbRNN(nn.Module):
        def __init__(self, kind: str):
            super().__init__()
            if kind == "lstm":
                self.rnn = nn.LSTM(N_FEAT, 24, batch_first=True)
            else:
                self.rnn = nn.GRU(N_FEAT, 24, batch_first=True)
            self.proj = nn.Linear(24, EMB_DIM)

        def forward(self, seq: torch.Tensor) -> torch.Tensor:
            out, _ = self.rnn(seq)
            h = out[:, -1, :]
            z = self.proj(h)
            return z / (z.norm(dim=-1, keepdim=True) + 1e-8)

    def _fit_one(x_tr, y_tr, x_te):
        mean, std = _fit_norm(x_tr)
        x_trn = _apply_norm(x_tr, mean, std)
        x_ten = _apply_norm(x_te, mean, std)
        model = EmbRNN(kind)
        opt = torch.optim.Adam(model.parameters(), lr=2e-2)
        xt = torch.from_numpy(x_trn)
        yt = torch.from_numpy(y_tr.astype(np.float32))
        model.train()
        for _ in range(epochs):
            opt.zero_grad()
            emb = model(xt)
            g_mask = yt > 0.5
            center = emb[g_mask].mean(dim=0)
            center = center / (center.norm() + 1e-8)
            sim = (emb * center).sum(dim=-1).clamp(-1, 1)
            loss = nn.functional.mse_loss((sim + 1) * 0.5, yt)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            emb_tr = model(xt)
            profile = emb_tr[g_mask].mean(dim=0)
            profile = profile / (profile.norm() + 1e-8)
            emb_te = model(torch.from_numpy(x_ten))
            sim = (emb_te * profile).sum(dim=-1).clamp(-1, 1)
            return ((sim + 1) * 0.5).numpy()

    torch.manual_seed(SEED)
    kind = "lstm" if name == "lstm" else "gru"
    scores = np.zeros(len(y), dtype=np.float64)
    for fi, te_mask in enumerate(_stratified_folds(y, folds)):
        print(f"    {name} fold {fi + 1}/{folds}", flush=True)
        tr = ~te_mask
        scores[te_mask] = _fit_one(x[tr], y[tr], x[te_mask])

    # Final model on all data for export
    mean, std = _fit_norm(x)
    xn = _apply_norm(x, mean, std)
    model = EmbRNN(kind)
    opt = torch.optim.Adam(model.parameters(), lr=2e-2)
    xt = torch.from_numpy(xn)
    yt = torch.from_numpy(y.astype(np.float32))
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        emb = model(xt)
        g_mask = yt > 0.5
        center = emb[g_mask].mean(dim=0)
        center = center / (center.norm() + 1e-8)
        sim = (emb * center).sum(dim=-1).clamp(-1, 1)
        loss = nn.functional.mse_loss((sim + 1) * 0.5, yt)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        emb_all = model(xt).numpy()
    profile = emb_all[y == 1].mean(axis=0).astype(np.float32)

    return _metrics(y, scores, name), model, mean, std, profile


# ── Windowed GBM ─────────────────────────────────────────────────────────────

def _train_gbm_loocv(
    x: np.ndarray, y: np.ndarray
) -> tuple[CandidateResult, object]:
    """Windowed gradient boosting (sklearn GBM — portable ONNX export)."""
    from sklearn.ensemble import GradientBoostingClassifier

    n = len(y)
    scores = np.zeros(n, dtype=np.float64)
    feats = np.stack([window_stat_features(w) for w in x])

    for i in range(n):
        tr = np.ones(n, dtype=bool)
        tr[i] = False
        clf = GradientBoostingClassifier(
            max_depth=2,
            n_estimators=40,
            learning_rate=0.1,
            random_state=SEED,
        )
        clf.fit(feats[tr], y[tr])
        proba = clf.predict_proba(feats[i : i + 1])[0]
        if 1 in clf.classes_:
            scores[i] = float(proba[list(clf.classes_).index(1)])
        else:
            scores[i] = float(proba[-1])

    clf = GradientBoostingClassifier(
        max_depth=2,
        n_estimators=40,
        learning_rate=0.1,
        random_state=SEED,
    )
    clf.fit(feats, y)
    return _metrics(y, scores, "gbm"), clf


def _export_rnn_onnx(
    model, path: Path, mean: np.ndarray, std: np.ndarray
) -> None:
    import torch
    import torch.nn as nn

    class NormRNN(nn.Module):
        """Applies train-time normalization then RNN (matches live monitor)."""

        def __init__(self, inner, mean, std):
            super().__init__()
            self.inner = inner
            self.register_buffer("mean", torch.from_numpy(mean.astype(np.float32)))
            self.register_buffer("std", torch.from_numpy(std.astype(np.float32)))

        def forward(self, seq: torch.Tensor) -> torch.Tensor:
            x = (seq - self.mean) / self.std
            return self.inner(x)

    wrapped = NormRNN(model, mean, std).eval()
    dummy = torch.zeros(1, WINDOW, N_FEAT, dtype=torch.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapped,
        dummy,
        str(path),
        input_names=["input"],
        output_names=["embedding"],
        dynamo=False,
        opset_version=17,
    )


def _export_gbm_onnx(clf, path: Path) -> None:
    """Export sklearn HistGBM → ONNX via skl2onnx."""
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    n_feat = len(WINDOW_STAT_KEYS)
    onnx_model = convert_sklearn(
        clf,
        initial_types=[("input", FloatTensorType([None, n_feat]))],
        target_opset=12,
        options={id(clf): {"zipmap": False}},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(onnx_model.SerializeToString())


def _pick_winner(results: list[CandidateResult]) -> CandidateResult:
    # Primary: AUC; tie-break: separation then accuracy
    return sorted(
        results,
        key=lambda r: (r.auc, r.separation, r.accuracy),
        reverse=True,
    )[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=ROOT / "data/driver1/behavioral")
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument(
        "--real-data-dir",
        type=Path,
        default=None,
        help="Real CAN windows (behavioral/genuine|attack or genuine|attack)",
    )
    ap.add_argument(
        "--real-repeat",
        type=int,
        default=3,
        help="Oversample factor for real windows when merging with synth",
    )
    args = ap.parse_args()

    x, y, paths, n_real = _load_windows(
        args.data, real_data_dir=args.real_data_dir, real_repeat=args.real_repeat
    )
    _warn_zero_real_samples(n_real)
    print(
        f"Loaded {len(y)} windows ({int(y.sum())} genuine, {int((1 - y).sum())} attack) "
        f"· real_windows={n_real} (pre-repeat)",
        flush=True,
    )
    print(f"Features ({N_FEAT}): {', '.join(BEHAVIORAL_FEATURE_KEYS)}", flush=True)

    results: list[CandidateResult] = []
    artifacts: dict = {}

    print("\n=== bake-off (RNN 5-fold CV · GBM LOO) ===", flush=True)
    for name in ("lstm", "gru"):
        print(f"  training {name}…", flush=True)
        metrics, model, mean, std, profile = _train_rnn_cv(
            name, x, y, epochs=args.epochs
        )
        results.append(metrics)
        artifacts[name] = {
            "model": model,
            "mean": mean,
            "std": std,
            "profile": profile,
        }
        print(
            f"    AUC={metrics.auc:.4f}  acc={metrics.accuracy:.3f}  "
            f"sep={metrics.separation:.3f}  "
            f"(genuine={metrics.genuine_mean:.3f} attack={metrics.attack_mean:.3f})",
            flush=True,
        )

    print("  training gbm…", flush=True)
    gbm_metrics, gbm_clf = _train_gbm_loocv(x, y)
    results.append(gbm_metrics)
    artifacts["gbm"] = {"clf": gbm_clf}
    print(
        f"    AUC={gbm_metrics.auc:.4f}  acc={gbm_metrics.accuracy:.3f}  "
        f"sep={gbm_metrics.separation:.3f}  "
        f"(genuine={gbm_metrics.genuine_mean:.3f} attack={gbm_metrics.attack_mean:.3f})",
        flush=True,
    )

    winner = _pick_winner(results)
    print(f"\nWinner: {winner.name} (AUC={winner.auc:.4f}, sep={winner.separation:.3f})")

    store = args.store
    store.mkdir(parents=True, exist_ok=True)
    onnx_path = store / "behavioral_model.onnx"
    legacy_path = store / "behavioral_lstm_int8.onnx"

    if winner.name in ("lstm", "gru"):
        art = artifacts[winner.name]
        _export_rnn_onnx(art["model"], onnx_path, art["mean"], art["std"])
        save_embedding(store, f"behavioral/{args.driver_id}.enc", art["profile"])
        score_mode = "cosine"
        arch = winner.name
        feat_mean = art["mean"].tolist()
        feat_std = art["std"].tolist()
    else:
        _export_gbm_onnx(artifacts["gbm"]["clf"], onnx_path)
        # GBM has no embedding profile; write a dummy 1-d template so load()
        # still sees an enrolled profile. Scoring uses classifier proba only.
        save_embedding(
            store, f"behavioral/{args.driver_id}.enc", np.ones(1, dtype=np.float32)
        )
        score_mode = "proba"
        arch = "gbm"
        feat_mean = None
        feat_std = None

    # Keep legacy filename so older loaders still find a model file.
    legacy_path.write_bytes(onnx_path.read_bytes())

    meta = {
        "arch": arch,
        "score_mode": score_mode,
        "winner": asdict(winner),
        "bakeoff": [asdict(r) for r in results],
        "feature_keys": list(BEHAVIORAL_FEATURE_KEYS),
        "window": WINDOW,
        "emb_dim": EMB_DIM if score_mode == "cosine" else None,
        "window_stat_keys": list(WINDOW_STAT_KEYS) if arch == "gbm" else None,
        "feat_mean": feat_mean,
        "feat_std": feat_std,
        "data_dir": str(args.data),
        "n_windows": int(len(y)),
        "n_genuine": int(y.sum()),
        "n_attack": int((1 - y).sum()),
        "n_real_windows": int(n_real),
        "real_data_dir": str(args.real_data_dir) if args.real_data_dir else None,
        "note": (
            "Trained with real windows mixed in."
            if n_real > 0
            else (
                "Trained on current behavioral windows (likely synth). "
                "Re-bake when real CAN arrives before trusting metrics."
            )
        ),
        "files": paths,
    }
    meta_path = store / "behavioral_bakeoff.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {onnx_path}")
    print(f"Wrote {legacy_path} (legacy alias)")
    print(f"Wrote {store / 'behavioral' / (args.driver_id + '.enc')}")
    print(f"Wrote {meta_path}")

    # Quick ORT smoke
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        inp = sess.get_inputs()[0]
        print(f"ORT smoke OK: input={inp.name} shape={inp.shape}")
    except Exception as exc:
        print(f"ORT smoke warning: {exc}")


if __name__ == "__main__":
    main()
