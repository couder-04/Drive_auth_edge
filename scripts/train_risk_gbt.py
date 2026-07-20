#!/usr/bin/env python3
"""Phase 2b — train the risk GBT head from txns.csv -> risk_gbt.onnx.

This is the v2 trainer that closes findings #1, #2, #4/#6, #5, #7, #10 from
docs/pipeline-review-2026-07.md plus writes the two sidecar JSONs consumed by
the v2 RiskModel (for #8 and #9). Changes vs. the v1 trainer:

  #1  Reads the FULL feature schema from the CSV -- ignition_on, is_tunnel,
      behavioral_score are real training inputs instead of hardcoded zeros.
      ``dist_from_home_km`` remains raw CSV telemetry (feeds ``out_of_zone``
      via ``in_trusted_zone``) but is not a model feature (Phase 0: retired
      after /50 scale mismatch vs 3–15 km training zones). Missing columns
      default gracefully so v1 CSVs still train.
  #2  Stratified train/val split with early stopping. Reports both train
      AND val AUC / accuracy; val is what should be published.
  #4/#6  Per-driver amount_z (using ``driver_id`` when the CSV supplies it)
      instead of a single global legit mean/std. Matches how inference
      computes amount_z via ProfileStore.apply_to_context, so the model no
      longer sees a fundamentally different distribution at serve time.
      When no ``driver_id`` column is present (v1 CSVs) we transparently
      fall back to the global baseline.
  #5  Post-processes the ONNX graph to relax the ``label`` output shape from
      ``[1]`` to ``[None]``, so batched inference no longer emits a per-call
      shape warning from onnxruntime.
  #7  Adds monotone constraints (+1 on every feature). Every DriveAuth
      feature is designed such that "more of it" -> "higher risk", so a
      monotonic GBT is strictly more defensible than one that can learn
      "higher amount -> lower risk" on an unlucky split.
  #10 Reports calibration quality on the val set (Brier score + a 10-bin
      reliability histogram) in the meta JSON so integrators can decide
      whether to tighten policy thresholds against actual model behaviour.
  #8  Writes ``risk_gbt_fallback_weights.json`` next to the ONNX, derived
      from the trained model's normalised feature importances. RiskModel
      picks this up so the additive fallback matches what the trained
      model actually learned when the ONNX ever fails to load.
  #9  ``risk_gbt.json`` (the trainer's meta report) now includes
      ``feature_importances_gain`` in a stable shape; RiskModel reads it to
      filter which reasons it surfaces so audit output stays consistent
      with the deployed model.

Usage:
  pip install lightgbm onnxmltools onnx skl2onnx scikit-learn
  python scripts/train_risk_gbt.py \\
    --csv data/driver1/transaction/txns.csv \\
    --out driveauth_store_phase2a/risk_gbt.onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.risk_model import RiskModel  # noqa: E402

FEATURE_ORDER = RiskModel._FEATURE_ORDER
TRAINER_VERSION = "v2"


# ── feature engineering (mirrors RiskModel._features + review fixes) ────────

def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def _get(row: dict, key: str, default: str = "") -> str:
    v = row.get(key, default)
    return v if v not in (None, "") else default


def _row_to_features(
    row: dict, amount_mean: float, amount_std: float
) -> dict[str, float]:
    """Mirrors ``RiskModel._features()`` verbatim, plus the "optional column"
    graceful-default logic for CSVs that predate the full schema."""
    amount = float(row["amount"])
    beneficiary_known = int(row["beneficiary_known"])
    hour = float(row["hour"])
    speed_kmh = float(row["speed_kmh"])
    in_trusted_zone = int(row["in_trusted_zone"])

    # dist_from_home_km stays on the CSV for telemetry / QA; geo risk uses
    # out_of_zone (from in_trusted_zone) only — see RiskModel module docstring.
    ignition_on = int(_get(row, "ignition_on", "1"))
    is_tunnel = int(_get(row, "is_tunnel", "0"))
    beh_raw = _get(row, "behavioral_score", "")
    behavioral_score = float(beh_raw) if beh_raw else None

    amount_z = 0.0
    if amount_std > 1e-6:
        amount_z = (amount - amount_mean) / amount_std
    amount_z = float(np.clip(amount_z, -3.0, 6.0))

    night = 1.0 if (hour < 5.0 or hour >= 23.0) else 0.0
    moving_fast = _clip01((speed_kmh - 20.0) / 80.0)

    return {
        "amount_z": amount_z,
        "amount_norm": _clip01(amount / 100_000.0),
        "beneficiary_novel": 0.0 if beneficiary_known else 1.0,
        "out_of_zone": 0.0 if in_trusted_zone else 1.0,
        "night": night,
        "moving_fast": moving_fast,
        "ignition_off_anomaly": 0.0 if ignition_on else 1.0,
        "tunnel": 1.0 if is_tunnel else 0.0,
        "behavior_anomaly": (
            _clip01(1.0 - behavioral_score) if behavioral_score is not None else 0.0
        ),
    }


def _driver_amount_stats(
    rows: list[dict], min_legit: int
) -> tuple[float, float, dict[str, tuple[float, float]]]:
    """
    Compute the global legit amount mean/std AND a per-driver map when the CSV
    supplies driver_id (review fix #4/#6). Drivers with fewer than
    ``min_legit`` legit rows fall back to the global stats -- their per-driver
    stats would be too noisy to use as an anchor.
    """
    legit_amounts_all = [
        float(r["amount"]) for r in rows if r["label"].strip().lower() == "legit"
    ]
    global_mean = float(np.mean(legit_amounts_all)) if legit_amounts_all else 0.0
    global_std = (
        float(np.std(legit_amounts_all)) if len(legit_amounts_all) > 1 else 1.0
    )

    per_driver: dict[str, tuple[float, float]] = {}
    if "driver_id" in rows[0]:
        by_driver: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            if r["label"].strip().lower() == "legit":
                by_driver[r["driver_id"]].append(float(r["amount"]))
        for did, amts in by_driver.items():
            if len(amts) >= min_legit:
                m = float(np.mean(amts))
                s = float(np.std(amts))
                # Guard against s=0 for a driver whose legit amounts are all
                # identical; treat as global (rare but happens on tiny slices).
                if s > 1e-6:
                    per_driver[did] = (m, s)
    return global_mean, global_std, per_driver


def load_csv(
    path: Path, min_legit_per_driver: int = 5
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Return (X, y, driver_id_ints, meta)."""
    X, y, driver_ids, meta, _weights = load_csv_with_weights(
        path, min_legit_per_driver=min_legit_per_driver
    )
    return X, y, driver_ids, meta


def load_csv_with_weights(
    path: Path,
    min_legit_per_driver: int = 5,
    *,
    extra_rows: list[dict] | None = None,
    real_row_count: int = 0,
    real_weight: float = 3.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict, np.ndarray]:
    """Like ``load_csv`` but returns sample weights (real rows weighted higher)."""
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if extra_rows:
        rows = list(rows) + list(extra_rows)
    if not rows:
        raise SystemExit(f"no rows in {path}")

    n_synth = len(rows) - int(real_row_count)
    global_mean, global_std, per_driver = _driver_amount_stats(
        rows, min_legit=min_legit_per_driver
    )

    driver_to_int: dict[str, int] = {}
    X, y, driver_ids, weights = [], [], [], []
    for i, r in enumerate(rows):
        did = r.get("driver_id", "_global_")
        drv_mean, drv_std = per_driver.get(did, (global_mean, global_std))
        feats = _row_to_features(r, drv_mean, drv_std)
        X.append([feats[k] for k in FEATURE_ORDER])
        label = r["label"].strip().lower()
        y.append(1 if label in ("suspicious", "fraud", "1") else 0)
        if did not in driver_to_int:
            driver_to_int[did] = len(driver_to_int)
        driver_ids.append(driver_to_int[did])
        is_real = i >= n_synth
        weights.append(float(real_weight) if is_real else 1.0)

    sample = rows[0]
    optional_present = {
        k: (k in sample)
        for k in ("dist_from_home_km", "ignition_on", "is_tunnel", "behavioral_score")
    }

    meta = {
        "trainer_version": TRAINER_VERSION,
        "amount_mean_global_legit": global_mean,
        "amount_std_global_legit": global_std,
        "n": len(rows),
        "n_suspicious": int(sum(y)),
        "n_legit": int(len(y) - sum(y)),
        "n_real": int(real_row_count),
        "n_synth": int(n_synth),
        "real_weight": float(real_weight) if real_row_count else 1.0,
        "feature_order": list(FEATURE_ORDER),
        "optional_columns_present": optional_present,
        "per_driver_amount_stats": {
            "n_drivers_total": len(driver_to_int),
            "n_drivers_with_per_driver_stats": len(per_driver),
            "min_legit_per_driver": min_legit_per_driver,
        },
    }
    return (
        np.asarray(X, dtype=np.float32),
        np.asarray(y, dtype=np.int32),
        np.asarray(driver_ids, dtype=np.int64),
        meta,
        np.asarray(weights, dtype=np.float64),
    )


def _load_real_txn_rows(real_data_dir: Path) -> list[dict]:
    """Collect txn CSVs under a pilot dump (txns_real.csv or any *.csv with label)."""
    rows: list[dict] = []
    if not real_data_dir.is_dir():
        return rows
    candidates = sorted(real_data_dir.rglob("txns_real.csv")) + sorted(
        real_data_dir.rglob("txns.csv")
    )
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        with path.open(newline="") as f:
            part = list(csv.DictReader(f))
        if part and "amount" in part[0] and "label" in part[0]:
            rows.extend(part)
    return rows


def _warn_zero_real_samples(n_real: int, *, context: str) -> None:
    if n_real > 0:
        return
    banner = (
        "\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
        f"! WARNING: {context} used ZERO real samples.\n"
        "! Metrics remain synthetic-only — not production-ready.\n"
        "! Collect fleet logs via hardware/can_logger.py and pass\n"
        "! --real-data-dir before trusting AUC / bake-off winners.\n"
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
    )
    print(banner, flush=True)


# ── training ────────────────────────────────────────────────────────────────

def train_lightgbm(X_tr, y_tr, X_va, y_va, seed: int, sample_weight=None):
    import lightgbm as lgb

    # Review fix #7: all DriveAuth features are designed so that "higher value
    # => higher risk" -- monotone constraints keep unlucky splits from
    # learning perverse patterns like "higher amount -> lower risk".
    monotone = [1] * len(FEATURE_ORDER)

    model = lgb.LGBMClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        num_leaves=15,
        min_child_samples=20,
        subsample=0.9,
        colsample_bytree=0.9,
        class_weight="balanced",
        random_state=seed,
        verbosity=-1,
        monotone_constraints=monotone,
    )
    fit_kw = {}
    if sample_weight is not None:
        fit_kw["sample_weight"] = sample_weight
    model.fit(
        X_tr,
        y_tr,
        eval_set=[(X_va, y_va)],
        callbacks=[lgb.early_stopping(30, verbose=False)],
        **fit_kw,
    )
    return model, "lightgbm"


def train_sklearn(X_tr, y_tr, X_va, y_va, seed: int, sample_weight=None):
    from sklearn.ensemble import HistGradientBoostingClassifier

    monotone = [1] * len(FEATURE_ORDER)
    model = HistGradientBoostingClassifier(
        max_depth=5,
        learning_rate=0.05,
        max_iter=400,
        min_samples_leaf=20,
        random_state=seed,
        class_weight="balanced",
        early_stopping=True,
        monotonic_cst=monotone,
    )
    # HistGradientBoostingClassifier supports sample_weight in fit.
    if sample_weight is not None:
        model.fit(X_tr, y_tr, sample_weight=sample_weight)
    else:
        model.fit(X_tr, y_tr)
    return model, "sklearn_hist_gbt"


# ── ONNX export + label-shape fix (review #5) ──────────────────────────────

def _patch_onnx_label_shape(onx) -> None:
    """
    Relax the ``label`` output shape from ``[1]`` to ``[None]``.

    Without this, batched inference emits::

        [W:onnxruntime] Expected shape from model of {1} does not match actual
        shape of {N} for output label

    once per call. Harmless (RiskModel reads from ``probabilities``) but noisy
    in logs. We fix it directly in the ONNX graph output metadata.
    """
    for output in onx.graph.output:
        if output.name == "label":
            tt = output.type.tensor_type
            if tt.shape.dim:
                # Turn the first dim into a symbolic batch dim.
                dim0 = tt.shape.dim[0]
                dim0.ClearField("dim_value")
                dim0.dim_param = "N"


def export_onnx(model, backend: str, out_path: Path, n_features: int) -> None:
    if backend == "lightgbm":
        from onnxmltools import convert_lightgbm
        from onnxmltools.convert.common.data_types import FloatTensorType

        onx = convert_lightgbm(
            model,
            initial_types=[("float_input", FloatTensorType([None, n_features]))],
            target_opset=12,
            zipmap=False,
        )
    else:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType

        onx = convert_sklearn(
            model,
            initial_types=[("float_input", FloatTensorType([None, n_features]))],
            target_opset=12,
            options={id(model): {"zipmap": False}},
        )
    _patch_onnx_label_shape(onx)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(onx.SerializeToString())


def evaluate_onnx(path: Path, X: np.ndarray, y: np.ndarray) -> dict:
    """Row-by-row inference (production path is batch=1)."""
    import onnxruntime as ort
    from sklearn.metrics import roc_auc_score

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    risks = np.empty(len(X), dtype=np.float64)
    for i in range(len(X)):
        outs = sess.run(None, {name: X[i : i + 1].astype(np.float32)})
        if len(outs) >= 2:
            prob = np.asarray(outs[1]).reshape(-1, 2)
            risks[i] = float(prob[0, 1])
        else:
            arr = np.asarray(outs[0]).ravel()
            risks[i] = float(arr[1] if arr.size >= 2 else arr[0])

    pred = (risks >= 0.5).astype(int)
    auc = float(roc_auc_score(y, risks)) if len(set(y.tolist())) > 1 else float("nan")
    return {
        "onnx_acc@0.5": round(float((pred == y).mean()), 4),
        "onnx_auc": round(auc, 4),
        "onnx_mean_risk_legit": (
            round(float(risks[y == 0].mean()), 4) if (y == 0).any() else None
        ),
        "onnx_mean_risk_suspicious": (
            round(float(risks[y == 1].mean()), 4) if (y == 1).any() else None
        ),
    }


# ── calibration report (review #10) ─────────────────────────────────────────

def calibration_report(y_true: np.ndarray, p_pred: np.ndarray, n_bins: int = 10) -> dict:
    """
    Reliability diagram (equal-width bins) + Brier score on the val set.

    We don't apply in-graph calibration here -- LightGBM through onnxmltools
    doesn't cleanly support post-hoc CalibratedClassifierCV wrapping. Instead
    we measure calibration and hand the numbers to the operator, who can
    tighten the policy thresholds (``RISK_APPROVE`` / ``RISK_REJECT``) against
    observed model behaviour rather than assumed calibrated probabilities.
    """
    from sklearn.metrics import brier_score_loss

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(p_pred, bins) - 1
    idx = np.clip(idx, 0, n_bins - 1)
    reliability = []
    for b in range(n_bins):
        mask = idx == b
        n_b = int(mask.sum())
        if n_b == 0:
            reliability.append(
                {"bin_lo": float(bins[b]), "bin_hi": float(bins[b + 1]),
                 "n": 0, "mean_pred": None, "frac_positive": None}
            )
            continue
        reliability.append({
            "bin_lo": float(bins[b]),
            "bin_hi": float(bins[b + 1]),
            "n": n_b,
            "mean_pred": round(float(p_pred[mask].mean()), 4),
            "frac_positive": round(float(y_true[mask].mean()), 4),
        })
    return {
        "brier_score": round(float(brier_score_loss(y_true, p_pred)), 6),
        "reliability_bins": reliability,
    }


# ── fallback-weights sidecar (review #8) ────────────────────────────────────

def _importances_to_fallback_weights(importances: dict[str, float]) -> dict[str, float]:
    """
    Turn LightGBM's gain-based importances into additive-fallback weights that
    (a) sum to 1.0 and (b) use the ``amount_z_scaled`` key that the additive
    fallback reads, since amount_z is the one feature that gets a nonlinear
    ``clip01(x/4)`` transform in the fallback path.
    """
    total = float(sum(importances.values())) or 1.0
    out: dict[str, float] = {}
    for name in FEATURE_ORDER:
        key = "amount_z_scaled" if name == "amount_z" else name
        out[key] = round(importances.get(name, 0.0) / total, 6)
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Train risk_gbt.onnx (v2)")
    parser.add_argument(
        "--csv",
        default=str(ROOT / "data" / "driver1" / "transaction" / "txns.csv"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "driveauth_store_phase2a" / "risk_gbt.onnx"),
    )
    parser.add_argument(
        "--backend", choices=("auto", "lightgbm", "sklearn"), default="auto",
    )
    parser.add_argument("--val-frac", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-legit-per-driver", type=int, default=5)
    parser.add_argument(
        "--real-data-dir",
        type=str,
        default="",
        help="Directory of real txn CSVs (txns_real.csv) to merge; weighted higher",
    )
    parser.add_argument("--real-weight", type=float, default=3.0)
    args = parser.parse_args()

    real_rows: list[dict] = []
    if args.real_data_dir:
        real_rows = _load_real_txn_rows(Path(args.real_data_dir))
    X, y, driver_ids, meta, sample_weights = load_csv_with_weights(
        Path(args.csv),
        min_legit_per_driver=args.min_legit_per_driver,
        extra_rows=real_rows or None,
        real_row_count=len(real_rows),
        real_weight=args.real_weight,
    )
    _warn_zero_real_samples(meta.get("n_real", 0), context="train_risk_gbt")
    print(f"Loaded {meta['n']} rows · legit={meta['n_legit']} suspicious={meta['n_suspicious']}")
    print(f"         real={meta.get('n_real', 0)} synth={meta.get('n_synth', meta['n'])} "
          f"real_weight={meta.get('real_weight', 1.0)}")
    print(f"amount_mean_global={meta['amount_mean_global_legit']:.1f} "
          f"amount_std_global={meta['amount_std_global_legit']:.1f}")
    print(f"optional cols present: {meta['optional_columns_present']}")
    print(f"per-driver stats: {meta['per_driver_amount_stats']}")

    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score, accuracy_score

    X_tr, X_va, y_tr, y_va, w_tr, w_va = train_test_split(
        X,
        y,
        sample_weights,
        test_size=args.val_frac,
        random_state=args.seed,
        stratify=y,
    )

    backend = args.backend
    if backend == "auto":
        try:
            import lightgbm  # noqa: F401
            backend = "lightgbm"
        except ImportError:
            backend = "sklearn"

    if backend == "lightgbm":
        try:
            model, used = train_lightgbm(
                X_tr, y_tr, X_va, y_va, args.seed, sample_weight=w_tr
            )
        except Exception as exc:
            print(f"LightGBM failed ({exc}) — falling back to sklearn")
            model, used = train_sklearn(
                X_tr, y_tr, X_va, y_va, args.seed, sample_weight=w_tr
            )
            backend = "sklearn"
    else:
        model, used = train_sklearn(
            X_tr, y_tr, X_va, y_va, args.seed, sample_weight=w_tr
        )
    # In-memory metrics
    p_tr = model.predict_proba(X_tr)[:, 1]
    p_va = model.predict_proba(X_va)[:, 1]
    train_auc = float(roc_auc_score(y_tr, p_tr))
    val_auc = float(roc_auc_score(y_va, p_va))
    train_acc = float(accuracy_score(y_tr, p_tr >= 0.5))
    val_acc = float(accuracy_score(y_va, p_va >= 0.5))
    print(f"\nIN-MEMORY  train_auc={train_auc:.4f}  val_auc={val_auc:.4f}")
    print(f"           train_acc@0.5={train_acc:.4f}  val_acc@0.5={val_acc:.4f}")
    print(f"           mean_risk_legit(val)={p_va[y_va==0].mean():.3f}  "
          f"mean_risk_suspicious(val)={p_va[y_va==1].mean():.3f}")

    calib = calibration_report(y_va, p_va)
    print(f"           brier={calib['brier_score']:.4f}")

    out = Path(args.out)
    export_onnx(model, "lightgbm" if used == "lightgbm" else "sklearn", out, X.shape[1])
    onnx_val = evaluate_onnx(out, X_va, y_va)
    print(f"\nONNX/val    {onnx_val}")

    # Feature importances
    feat_imps: dict[str, float] = {}
    if hasattr(model, "feature_importances_"):
        for name, imp in zip(FEATURE_ORDER, model.feature_importances_):
            feat_imps[name] = float(imp)
    if feat_imps:
        print("\nFeature importances (gain):")
        for name, imp in sorted(feat_imps.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<22s} {imp:.1f}")

    # Sidecar #1: additive-fallback weights (review fix #8)
    fallback_weights = _importances_to_fallback_weights(feat_imps) if feat_imps else None
    if fallback_weights:
        fb_path = out.parent / "risk_gbt_fallback_weights.json"
        fb_path.write_text(json.dumps({
            "trainer_version": TRAINER_VERSION,
            "source": "normalised feature_importances_gain from trained model",
            "weights": fallback_weights,
        }, indent=2) + "\n")
        print(f"Wrote {fb_path}")

    # Sidecar #2: full meta report (also carries feature_importances_gain for
    # RiskModel's importance-aware _reasons(); review fix #9)
    meta_path = out.with_suffix(".json")
    report = {
        "backend": used,
        "trainer_version": TRAINER_VERSION,
        "onnx": str(out),
        "csv": args.csv,
        "seed": args.seed,
        "val_frac": args.val_frac,
        **meta,
        "train_auc": round(train_auc, 4),
        "val_auc": round(val_auc, 4),
        "train_acc@0.5": round(train_acc, 4),
        "val_acc@0.5": round(val_acc, 4),
        "val_mean_risk_legit": round(float(p_va[y_va == 0].mean()), 4),
        "val_mean_risk_suspicious": round(float(p_va[y_va == 1].mean()), 4),
        "feature_importances_gain": {k: int(round(v)) for k, v in feat_imps.items()},
        "calibration": calib,
        **onnx_val,
    }
    meta_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {out}")
    print(f"Wrote {meta_path}")


if __name__ == "__main__":
    main()
