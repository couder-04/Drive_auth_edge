"""Shared helpers for Stage 2 bio calibrator / PAD trainers."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load_wav(path: Path, sr: int = 16_000) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
        if w.getframerate() != sr:
            ratio = sr / w.getframerate()
            idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        return audio.astype(np.float32)


def far_frr(genuine: list[float], attack: list[float], thr: float) -> tuple[float, float]:
    g = np.asarray(genuine, dtype=np.float64)
    a = np.asarray(attack, dtype=np.float64)
    frr = float(np.mean(g < thr)) if g.size else float("nan")
    far = float(np.mean(a >= thr)) if a.size else float("nan")
    return far, frr


def eer_metrics(genuine: list[float], attack: list[float]) -> dict:
    if not genuine:
        return {}
    g = np.asarray(genuine, dtype=np.float64)
    a = np.asarray(attack, dtype=np.float64) if attack else np.asarray([0.0])
    best_gap, eer_thr, eer_far, eer_frr = 1.0, 0.5, 1.0, 1.0
    for thr in np.linspace(0.0, 1.0, 1001):
        far, frr = far_frr(g.tolist(), a.tolist(), float(thr))
        gap = abs(far - frr)
        if gap < best_gap:
            best_gap, eer_thr, eer_far, eer_frr = gap, float(thr), far, frr
    return {
        "eer_thr": round(eer_thr, 4),
        "eer": round((eer_far + eer_frr) / 2.0, 4),
        "eer_far": round(eer_far, 4),
        "eer_frr": round(eer_frr, 4),
    }


def summarize(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0}
    a = np.asarray(scores, dtype=np.float64)
    return {
        "n": int(a.size),
        "mean": round(float(a.mean()), 4),
        "p10": round(float(np.percentile(a, 10)), 4),
        "p50": round(float(np.percentile(a, 50)), 4),
        "p90": round(float(np.percentile(a, 90)), 4),
        "min": round(float(a.min()), 4),
        "max": round(float(a.max()), 4),
    }


def export_logreg_onnx(clf, out_path: Path, n_features: int) -> None:
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    onx = convert_sklearn(
        clf,
        initial_types=[("float_input", FloatTensorType([None, n_features]))],
        target_opset=12,
        options={id(clf): {"zipmap": False}},
    )
    for output in onx.graph.output:
        if output.name == "label":
            tt = output.type.tensor_type
            if tt.shape.dim:
                dim0 = tt.shape.dim[0]
                dim0.ClearField("dim_value")
                dim0.dim_param = "N"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(onx.SerializeToString())


def train_logreg_loo(
    X: np.ndarray,
    y: np.ndarray,
    *,
    seed: int = 42,
    max_gap: float = 0.15,
) -> tuple[object, dict]:
    """Fit LogisticRegression with LOO AUC + train/val gap check."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import LeaveOneOut, train_test_split

    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y, dtype=np.int32)
    if len(np.unique(y)) < 2:
        raise SystemExit("Need both classes to train logreg head")

    loo = LeaveOneOut()
    loo_scores = np.zeros(len(y), dtype=np.float64)
    for tr, te in loo.split(X):
        clf = LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=2000,
            random_state=seed,
            solver="lbfgs",
        )
        clf.fit(X[tr], y[tr])
        loo_scores[te[0]] = float(clf.predict_proba(X[te])[0, 1])
    loo_auc = float(roc_auc_score(y, loo_scores))

    # Hold-out gap (may be tiny N — use max(0.25, 2 samples) stratified)
    test_size = max(2, int(round(0.25 * len(y))))
    if test_size >= len(y) - 1:
        test_size = max(1, len(y) // 4)
    X_tr, X_va, y_tr, y_va = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y
    )
    clf = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=2000,
        random_state=seed,
        solver="lbfgs",
    )
    clf.fit(X_tr, y_tr)
    p_tr = clf.predict_proba(X_tr)[:, 1]
    p_va = clf.predict_proba(X_va)[:, 1]
    train_auc = float(roc_auc_score(y_tr, p_tr)) if len(np.unique(y_tr)) > 1 else 1.0
    val_auc = float(roc_auc_score(y_va, p_va)) if len(np.unique(y_va)) > 1 else loo_auc
    gap = train_auc - val_auc

    # Final fit on all data for export
    final = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=2000,
        random_state=seed,
        solver="lbfgs",
    )
    final.fit(X, y)
    p_all = final.predict_proba(X)[:, 1]
    train_all_auc = float(roc_auc_score(y, p_all))

    # Shuffled-label sanity (should collapse toward 0.5)
    rng = np.random.default_rng(seed)
    y_shuf = y.copy()
    rng.shuffle(y_shuf)
    shuf_scores = np.zeros(len(y), dtype=np.float64)
    for tr, te in LeaveOneOut().split(X):
        c = LogisticRegression(
            C=1.0,
            class_weight="balanced",
            max_iter=2000,
            random_state=seed,
            solver="lbfgs",
        )
        y_tr_s = y_shuf[tr]
        if len(np.unique(y_tr_s)) < 2:
            shuf_scores[te[0]] = 0.5
            continue
        c.fit(X[tr], y_tr_s)
        shuf_scores[te[0]] = float(c.predict_proba(X[te])[0, 1])
    try:
        shuf_auc = float(roc_auc_score(y_shuf, shuf_scores))
    except ValueError:
        shuf_auc = 0.5

    meta = {
        "loo_auc": round(loo_auc, 4),
        "train_auc": round(train_auc, 4),
        "val_auc": round(val_auc, 4),
        "gap": round(gap, 4),
        "fit_all_auc": round(train_all_auc, 4),
        "shuffled_loo_auc": round(shuf_auc, 4),
        "n": int(len(y)),
        "n_pos": int((y == 1).sum()),
        "n_neg": int((y == 0).sum()),
        "coefficients": final.coef_[0].astype(float).tolist(),
        "intercept": float(final.intercept_[0]),
    }
    if gap > max_gap and loo_auc < 0.85:
        # Soft warning — LOO is the more trustworthy small-N metric
        meta["gap_warning"] = (
            f"train-val gap {gap:.3f} > {max_gap} (small-N holdout noisy; "
            f"LOO AUC={loo_auc:.3f})"
        )
    if abs(shuf_auc - 0.5) > 0.25 and loo_auc < 0.7:
        raise SystemExit(
            f"Overfit audit fail: shuffled LOO AUC={shuf_auc:.3f} "
            f"with weak real LOO={loo_auc:.3f}"
        )
    return final, meta


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def ort_smoke(path: Path, n_features: int) -> None:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    dummy = np.zeros((1, n_features), dtype=np.float32)
    outs = sess.run(None, {name: dummy})
    print(f"ORT smoke OK: {path.name} outs={len(outs)} in={name}")
