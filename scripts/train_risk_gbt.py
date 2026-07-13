#!/usr/bin/env python3
"""Phase 2b — train risk GBT from txns.csv → risk_gbt.onnx.

Uses LightGBM when available, else sklearn HistGradientBoosting.
Features match driveauth.risk_model.RiskModel._FEATURE_ORDER.

Usage:
  pip install lightgbm onnxmltools onnx skl2onnx  # or sklearn-only path
  python scripts/train_risk_gbt.py \\
    --csv data/driver1/transaction/txns.csv \\
    --out driveauth_store_phase2a/risk_gbt.onnx
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.risk_model import RiskModel  # noqa: E402

FEATURE_ORDER = RiskModel._FEATURE_ORDER


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


def row_to_features(
    *,
    amount: float,
    beneficiary_known: int,
    hour: float,
    speed_kmh: float,
    in_trusted_zone: int,
    amount_mean: float,
    amount_std: float,
) -> dict[str, float]:
    amount_z = 0.0
    if amount_std > 1e-6:
        amount_z = (amount - amount_mean) / amount_std
    amount_z = float(np.clip(amount_z, -3.0, 6.0))
    night = 1.0 if (hour < 5.0 or hour >= 23.0) else 0.0
    moving_fast = _clip01((speed_kmh - 20.0) / 80.0)
    # CSV has no dist/ignition/tunnel/behavior — use zone as weak dist proxy
    out_of_zone = 0.0 if in_trusted_zone else 1.0
    dist_from_home = 0.0 if in_trusted_zone else 0.7
    return {
        "amount_z": amount_z,
        "amount_norm": _clip01(amount / 100_000.0),
        "beneficiary_novel": 0.0 if beneficiary_known else 1.0,
        "dist_from_home": dist_from_home,
        "out_of_zone": out_of_zone,
        "night": night,
        "moving_fast": moving_fast,
        "ignition_off_anomaly": 0.0,
        "tunnel": 0.0,
        "behavior_anomaly": 0.0,
    }


def load_csv(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    rows = []
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    if not rows:
        raise SystemExit(f"no rows in {path}")

    legit_amounts = [
        float(r["amount"]) for r in rows if r["label"].strip().lower() == "legit"
    ]
    amount_mean = float(np.mean(legit_amounts)) if legit_amounts else 0.0
    amount_std = float(np.std(legit_amounts)) if len(legit_amounts) > 1 else 1.0

    X, y = [], []
    for r in rows:
        feats = row_to_features(
            amount=float(r["amount"]),
            beneficiary_known=int(r["beneficiary_known"]),
            hour=float(r["hour"]),
            speed_kmh=float(r["speed_kmh"]),
            in_trusted_zone=int(r["in_trusted_zone"]),
            amount_mean=amount_mean,
            amount_std=amount_std,
        )
        X.append([feats[k] for k in FEATURE_ORDER])
        label = r["label"].strip().lower()
        y.append(1 if label in ("suspicious", "fraud", "1") else 0)

    meta = {
        "amount_mean": amount_mean,
        "amount_std": amount_std,
        "n": len(rows),
        "n_suspicious": int(sum(y)),
        "n_legit": int(len(y) - sum(y)),
        "feature_order": list(FEATURE_ORDER),
    }
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.int32), meta


def train_lightgbm(X: np.ndarray, y: np.ndarray):
    import lightgbm as lgb

    # Small dataset — strong regularization
    model = lgb.LGBMClassifier(
        n_estimators=80,
        max_depth=3,
        learning_rate=0.08,
        num_leaves=8,
        min_child_samples=2,
        subsample=0.9,
        colsample_bytree=0.9,
        class_weight="balanced",
        random_state=42,
        verbosity=-1,
    )
    model.fit(X, y)
    return model, "lightgbm"


def train_sklearn(X: np.ndarray, y: np.ndarray):
    from sklearn.ensemble import HistGradientBoostingClassifier

    model = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.08,
        max_iter=80,
        min_samples_leaf=2,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X, y)
    return model, "sklearn_hist_gbt"


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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(onx.SerializeToString())


def smoke_onnx(path: Path, X: np.ndarray, y: np.ndarray) -> dict:
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    outs = sess.run(None, {name: X.astype(np.float32)})

    def row_risk(i: int) -> float:
        # Prefer second output probabilities [p0, p1]
        if len(outs) >= 2:
            prob = outs[1][i]
            if isinstance(prob, dict):
                return float(prob.get(1, prob.get("1", list(prob.values())[-1])))
            arr = np.asarray(prob, dtype=np.float64).ravel()
            return float(arr[1] if arr.size >= 2 else arr[0])
        arr = np.asarray(outs[0][i], dtype=np.float64).ravel()
        return float(arr[1] if arr.size >= 2 else arr[0])

    risk_a = np.asarray([row_risk(i) for i in range(len(X))], dtype=np.float64)
    pred = (risk_a >= 0.5).astype(int)
    acc = float((pred == y).mean())
    return {
        "train_acc@0.5": round(acc, 3),
        "mean_risk_legit": round(float(risk_a[y == 0].mean()), 3) if (y == 0).any() else None,
        "mean_risk_suspicious": round(float(risk_a[y == 1].mean()), 3) if (y == 1).any() else None,
        "outputs": [o.name for o in sess.get_outputs()],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train risk_gbt.onnx")
    parser.add_argument(
        "--csv",
        default=str(ROOT / "data" / "driver1" / "transaction" / "txns.csv"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "driveauth_store_phase2a" / "risk_gbt.onnx"),
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "lightgbm", "sklearn"),
        default="auto",
    )
    args = parser.parse_args()

    X, y, meta = load_csv(Path(args.csv))
    print(f"Loaded {meta['n']} rows · legit={meta['n_legit']} suspicious={meta['n_suspicious']}")
    print(f"amount_mean={meta['amount_mean']:.1f} amount_std={meta['amount_std']:.1f}")

    backend = args.backend
    if backend == "auto":
        try:
            import lightgbm  # noqa: F401

            backend = "lightgbm"
        except ImportError:
            backend = "sklearn"

    if backend == "lightgbm":
        try:
            model, used = train_lightgbm(X, y)
        except Exception as exc:
            print(f"LightGBM failed ({exc}) — falling back to sklearn")
            model, used = train_sklearn(X, y)
            backend = "sklearn"
    else:
        model, used = train_sklearn(X, y)

    out = Path(args.out)
    export_onnx(model, backend if used == "lightgbm" else "sklearn", out, X.shape[1])
    smoke = smoke_onnx(out, X, y)

    meta_path = out.with_suffix(".json")
    report = {
        "backend": used,
        "onnx": str(out),
        "csv": args.csv,
        **meta,
        **smoke,
    }
    meta_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {out}")
    print(f"Wrote {meta_path}")
    print(json.dumps(smoke, indent=2))
    print("\nPlace/copy into DRIVEAUTH_STORE_DIR as risk_gbt.onnx (done if --out points there).")


if __name__ == "__main__":
    main()
