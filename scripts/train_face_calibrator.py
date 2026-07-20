#!/usr/bin/env python3
"""Stage 2 — train face match-score calibrator (cosine × PAD → logreg).

Writes **only** under ``faces/{driver_id}/`` — never overwrites shared legacy
store-root artifacts or another driver's heads.

Usage:
  python scripts/train_face_calibrator.py --store driveauth_store_phase2a \\
      --data data/driver1 --driver-id driver1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.stage2_artifacts import (  # noqa: E402
    FACE_CALIBRATOR,
    FACE_PAD,
    resolve_bio_artifact,
    trainer_json_path,
    trainer_onnx_path,
)
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

    pad_ref = resolve_bio_artifact(args.store, args.driver_id, FACE_PAD)
    if pad_ref.path is None:
        raise SystemExit(
            f"face_pad.onnx missing for {args.driver_id} — "
            "run train_face_pad.py --driver-id … first"
        )
    pad = OnnxLogitHead.load(pad_ref.path)
    if pad is None:
        raise SystemExit(f"could not load PAD from {pad_ref.path}")

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
    print(
        f"face calibrator [{args.driver_id}]: n={len(y)} "
        f"pos={int(y.sum())} neg={int((1 - y).sum())}"
    )

    clf, meta = train_logreg_loo(X, y, seed=args.seed)
    out_onnx = trainer_onnx_path(args.store, args.driver_id, FACE_CALIBRATOR)
    out_json = trainer_json_path(args.store, args.driver_id, FACE_CALIBRATOR)
    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    meta.update(
        {
            "driver_id": args.driver_id,
            "feature_keys": list(FEATURE_KEYS),
            "files": paths,
            "onnx": str(out_onnx),
            "pad_source": pad_ref.source,
            "pad_path": str(pad_ref.path),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "note": "Face cosine×PAD calibrator (Stage 2, per-driver)",
        }
    )
    write_json(out_json, meta)
    print(f"Wrote {out_onnx}")
    print(f"LOO AUC={meta['loo_auc']} gap={meta['gap']}")


if __name__ == "__main__":
    main()
