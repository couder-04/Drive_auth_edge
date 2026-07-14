#!/usr/bin/env python3
"""Stage 2 — train face PAD head (hand-crafted features → logreg ONNX).

Usage:
  python scripts/train_face_pad.py --store driveauth_store_phase2a --data data/driver1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.matchers.face_pad_features import (  # noqa: E402
    FACE_PAD_FEATURE_KEYS,
    extract_face_pad_features,
)
from scripts._bio_train_common import (  # noqa: E402
    export_logreg_onnx,
    ort_smoke,
    train_logreg_loo,
    write_json,
)

ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")


def _load_meta_for(path: Path, fm) -> tuple[np.ndarray, dict]:
    import cv2

    bgr = cv2.imread(str(path))
    if bgr is None:
        raise ValueError(f"unreadable {path}")
    fm.inject_bgr(bgr)
    # Populate Haar / center-crop meta like production scoring
    _ = fm.capture_frame()
    meta = getattr(fm, "_last_meta", {}) or {}
    crop = meta.get("bgr")
    if crop is None:
        h, w = bgr.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        crop = bgr[y0 : y0 + side, x0 : x0 + side]
        meta = {"face_frac": 1.0, "frontal_ok": True, "bgr": crop}
    feats = extract_face_pad_features(
        crop,
        face_frac=meta.get("face_frac"),
        frontal_ok=meta.get("frontal_ok"),
    )
    return feats, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--target-apcer", type=float, default=0.25)
    ap.add_argument("--max-bpcer", type=float, default=0.25)
    args = ap.parse_args()

    import os

    os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"

    from driveauth.matchers.face import FaceMatcher

    fm = FaceMatcher.load(str(args.store), args.driver_id)
    if fm._session is None:
        raise SystemExit("FaceMatcher ONNX not loaded")

    xs: list[np.ndarray] = []
    ys: list[int] = []
    paths: list[str] = []

    for split, label in (
        ("enroll", 1),
        ("genuine", 1),
        *[(a, 0) for a in ATTACKS],
    ):
        folder = args.data / "face" / split
        for p in sorted(folder.glob("*.jpg")):
            try:
                feats, _ = _load_meta_for(p, fm)
            except Exception as exc:
                print(f"skip {p}: {exc}")
                continue
            xs.append(feats)
            ys.append(label)
            paths.append(str(p.relative_to(args.data)))

    X = np.stack(xs)
    y = np.asarray(ys, dtype=np.int32)
    print(f"face PAD: n={len(y)} bonafide={int(y.sum())} attack={int((1 - y).sum())}")

    clf, meta = train_logreg_loo(X, y, seed=args.seed)

    # Choose thr: prefer APCER≤target and BPCER≤max; else max Youden J.
    proba = clf.predict_proba(X)[:, 1]
    attack = y == 0
    bona = y == 1
    constrained: list[tuple[float, float, float, float]] = []
    youden_best = (-1.0, 0.5, 1.0, 1.0)
    for thr in np.linspace(0.05, 0.95, 91):
        pred_pass = proba >= thr
        apcer = float(pred_pass[attack].mean()) if attack.any() else 0.0
        bpcer = float((~pred_pass)[bona].mean()) if bona.any() else 0.0
        youden = (1.0 - apcer) - bpcer
        if youden > youden_best[0]:
            youden_best = (youden, float(thr), apcer, bpcer)
        if apcer <= args.target_apcer and bpcer <= args.max_bpcer:
            constrained.append((bpcer + apcer, float(thr), apcer, bpcer))
    if constrained:
        constrained.sort()
        _, best_thr, best_apcer, best_bpcer = constrained[0]
    else:
        _, best_thr, best_apcer, best_bpcer = youden_best

    out_onnx = args.store / "face_pad.onnx"
    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    meta.update(
        {
            "feature_keys": list(FACE_PAD_FEATURE_KEYS),
            "threshold": round(best_thr, 4),
            "apcer_at_thr": round(best_apcer, 4),
            "bpcer_at_thr": round(best_bpcer, 4),
            "target_apcer": args.target_apcer,
            "files": paths,
            "onnx": str(out_onnx),
            "note": "Hand-crafted PAD features + logreg (Stage 2)",
        }
    )
    write_json(args.store / "face_pad.json", meta)
    print(f"Wrote {out_onnx}")
    print(
        f"LOO AUC={meta['loo_auc']} thr={best_thr:.3f} "
        f"APCER={best_apcer:.3f} BPCER={best_bpcer:.3f}"
    )


if __name__ == "__main__":
    main()
