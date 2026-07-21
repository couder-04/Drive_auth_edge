#!/usr/bin/env python3
"""Stage 2 — train face PAD head (hand-crafted features → logreg ONNX).

Writes **only** under ``faces/{driver_id}/`` — never overwrites shared legacy
store-root artifacts or another driver's heads.

Usage:
  python scripts/train_face_pad.py --store driveauth_store_phase2a \\
      --data data/driver1 --driver-id driver1

Exclude Haar-miss / center-crop fallback samples (recommended when attack_side
fails detection and pollutes features)::

  python scripts/train_face_pad.py ... --exclude-fallback-crops
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.matchers.face_pad_features import (  # noqa: E402
    FACE_PAD_FEATURE_KEYS,
    extract_face_pad_features,
)
from driveauth.stage2_artifacts import FACE_PAD, trainer_json_path, trainer_onnx_path  # noqa: E402
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
    used_fallback = bool(meta.get("inject_fallback"))
    if crop is None:
        h, w = bgr.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        crop = bgr[y0 : y0 + side, x0 : x0 + side]
        meta = {
            "face_frac": None,
            "frontal_ok": False,
            "bgr": crop,
            "inject_fallback": True,
        }
        used_fallback = True
    feats = extract_face_pad_features(
        crop,
        face_frac=meta.get("face_frac"),
        frontal_ok=meta.get("frontal_ok"),
    )
    meta = dict(meta)
    meta["used_fallback_crop"] = used_fallback
    return feats, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--target-apcer", type=float, default=0.25)
    ap.add_argument("--max-bpcer", type=float, default=0.25)
    ap.add_argument(
        "--exclude-fallback-crops",
        action="store_true",
        help="Drop samples that used Haar-miss / center-crop fallback",
    )
    ap.add_argument(
        "--disable-if-loo-below",
        type=float,
        default=0.55,
        help="If LOO AUC ≤ this, mark pad_disabled in meta (matcher also gates)",
    )
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
    excluded: list[str] = []
    fallback_flags: list[bool] = []

    for split, label in (
        ("enroll", 1),
        ("genuine", 1),
        *[(a, 0) for a in ATTACKS],
    ):
        folder = args.data / "face" / split
        for p in sorted(folder.glob("*.jpg")):
            try:
                feats, meta = _load_meta_for(p, fm)
            except Exception as exc:
                print(f"skip {p}: {exc}")
                continue
            rel = str(p.relative_to(args.data))
            used_fb = bool(meta.get("used_fallback_crop"))
            if args.exclude_fallback_crops and used_fb:
                excluded.append(rel)
                print(f"exclude fallback crop: {rel}")
                continue
            xs.append(feats)
            ys.append(label)
            paths.append(rel)
            fallback_flags.append(used_fb)

    if len(xs) < 6:
        raise SystemExit(
            f"Need more face PAD samples (got {len(xs)}; excluded={len(excluded)})"
        )

    X = np.stack(xs)
    y = np.asarray(ys, dtype=np.int32)
    n_fallback_kept = int(sum(fallback_flags))
    print(
        f"face PAD [{args.driver_id}]: n={len(y)} bonafide={int(y.sum())} "
        f"attack={int((1 - y).sum())} fallback_in_train={n_fallback_kept} "
        f"excluded={len(excluded)}"
    )

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

    out_onnx = trainer_onnx_path(args.store, args.driver_id, FACE_PAD)
    out_json = trainer_json_path(args.store, args.driver_id, FACE_PAD)
    # Never write to store-root legacy paths
    if out_onnx.parent == Path(args.store):
        raise SystemExit("refusing to write face_pad to store root")

    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    loo = float(meta.get("loo_auc") or 0.0)
    pad_disabled = loo <= args.disable_if_loo_below
    meta.update(
        {
            "driver_id": args.driver_id,
            "feature_keys": list(FACE_PAD_FEATURE_KEYS),
            "threshold": round(best_thr, 4),
            "apcer_at_thr": round(best_apcer, 4),
            "bpcer_at_thr": round(best_bpcer, 4),
            "target_apcer": args.target_apcer,
            "files": paths,
            "excluded_fallback_crops": excluded,
            "exclude_fallback_crops": bool(args.exclude_fallback_crops),
            "fallback_crops_in_train": n_fallback_kept,
            "onnx": str(out_onnx),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "pad_disabled": pad_disabled,
            "note": (
                "Hand-crafted PAD features + logreg (Stage 2, per-driver). "
                + (
                    "PAD DISABLED — LOO AUC near chance; do not enforce."
                    if pad_disabled
                    else "Per-driver PAD head."
                )
            ),
        }
    )
    write_json(out_json, meta)
    print(f"Wrote {out_onnx}")
    print(
        f"LOO AUC={meta['loo_auc']} thr={best_thr:.3f} "
        f"APCER={best_apcer:.3f} BPCER={best_bpcer:.3f} "
        f"pad_disabled={pad_disabled}"
    )
    if excluded:
        print(f"Excluded {len(excluded)} fallback-crop sample(s):")
        for e in excluded:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
