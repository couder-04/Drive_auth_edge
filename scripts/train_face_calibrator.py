#!/usr/bin/env python3
"""Stage 2 — train face match-score calibrator (cosine × PAD → logreg).

Usage:
  python scripts/train_face_calibrator.py --store driveauth_store_phase2a
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._bio_train_common import (  # noqa: E402
    export_logreg_onnx,
    ort_smoke,
    train_logreg_loo,
    write_json,
)

ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")
FEATURE_KEYS = ("cosine", "pad_proba", "face_frac")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    # Raw cosine path; PAD head loaded separately for features
    os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.face_pad_features import extract_face_pad_features
    from driveauth.matchers.onnx_head import OnnxLogitHead

    fm = FaceMatcher.load(str(args.store), args.driver_id)
    if not fm.ready:
        raise SystemExit("FaceMatcher not ready")

    pad = OnnxLogitHead.load(args.store / "face_pad.onnx")
    if pad is None:
        raise SystemExit("face_pad.onnx missing — run train_face_pad.py first")

    import cv2

    xs: list[np.ndarray] = []
    ys: list[int] = []
    paths: list[str] = []

    def _score(path: Path, label: int) -> None:
        bgr = cv2.imread(str(path))
        if bgr is None:
            return
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if r.score is None:
            return
        meta = getattr(fm, "_last_meta", {}) or {}
        crop = meta.get("bgr")
        if crop is None:
            return
        pad_feats = extract_face_pad_features(
            crop,
            face_frac=meta.get("face_frac"),
            frontal_ok=meta.get("frontal_ok"),
        )
        pad_p = float(pad.predict_proba(pad_feats))
        feats = np.array(
            [float(r.score), pad_p, float(meta.get("face_frac") or 1.0)],
            dtype=np.float32,
        )
        xs.append(feats)
        ys.append(label)
        paths.append(str(path.relative_to(args.data)))

    for p in sorted((args.data / "face" / "genuine").glob("*.jpg")):
        _score(p, 1)
    for split in ATTACKS:
        for p in sorted((args.data / "face" / split).glob("*.jpg")):
            _score(p, 0)

    if len(xs) < 6:
        raise SystemExit(f"Need more face samples with match scores (got {len(xs)})")

    X = np.stack(xs)
    y = np.asarray(ys, dtype=np.int32)
    print(f"face calibrator: n={len(y)} pos={int(y.sum())} neg={int((1 - y).sum())}")

    clf, meta = train_logreg_loo(X, y, seed=args.seed)
    out_onnx = args.store / "face_calibrator.onnx"
    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    meta.update(
        {
            "feature_keys": list(FEATURE_KEYS),
            "files": paths,
            "onnx": str(out_onnx),
            "note": "Face cosine×PAD calibrator (Stage 2)",
        }
    )
    write_json(args.store / "face_calibrator.json", meta)
    print(f"Wrote {out_onnx}")
    print(f"LOO AUC={meta['loo_auc']} gap={meta['gap']}")


if __name__ == "__main__":
    main()
