#!/usr/bin/env python3
"""Stage 2 / Phase 4 — train trust-fusion logreg → trust_fusion.onnx.

Builds labeled multimodal rows from scored genuine/attack voice+face sets,
trains LogisticRegression, exports ONNX for TrustFusion.

Usage:
  python scripts/train_trust_fusion.py --store driveauth_store_phase2a
"""

from __future__ import annotations

import argparse
import itertools
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._bio_train_common import (  # noqa: E402
    export_logreg_onnx,
    load_wav,
    ort_smoke,
    train_logreg_loo,
    write_json,
)

FEATURE_KEYS = (
    "voice_score",
    "face_score",
    "finger_score",
    "voice_q",
    "face_q",
    "finger_q",
    "voice_avail",
    "face_avail",
    "finger_avail",
)


def _row(
    voice: float | None,
    face: float | None,
    finger: float | None = None,
    voice_q: float = 1.0,
    face_q: float = 1.0,
    finger_q: float = 1.0,
) -> np.ndarray:
    va = 1.0 if voice is not None else 0.0
    fa = 1.0 if face is not None else 0.0
    fia = 1.0 if finger is not None else 0.0
    return np.array(
        [
            float(voice or 0.0),
            float(face or 0.0),
            float(finger or 0.0),
            voice_q if va else 0.0,
            face_q if fa else 0.0,
            finger_q if fia else 0.0,
            va,
            fa,
            fia,
        ],
        dtype=np.float32,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-pairs", type=int, default=400)
    args = ap.parse_args()

    # Use Stage-2 wired matchers when present (calibrated scores)
    os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher
    from driveauth.quality_gate import score_voice

    vm = VoiceMatcher.load(
        str(args.store / "enroll"), args.driver_id, store_dir=str(args.store)
    )
    fm = FaceMatcher.load(str(args.store), args.driver_id)
    if not vm.ready or not fm.ready:
        raise SystemExit("Voice/Face matchers not ready")

    import cv2

    voice_pos: list[tuple[float, float]] = []
    voice_neg: list[tuple[float, float]] = []
    for p in sorted((args.data / "voice" / "genuine").glob("*.wav")):
        audio = load_wav(p)
        r = vm.score(audio)
        if r.score is None:
            continue
        _, q, _ = score_voice(audio)
        voice_pos.append((float(r.score), q))
    for split in ("attack_replay", "attack_silent", "attack_other_speaker"):
        for p in sorted((args.data / "voice" / split).glob("*.wav")):
            audio = load_wav(p)
            r = vm.score(audio)
            s = float(r.score) if r.score is not None else 0.0
            _, q, _ = score_voice(audio)
            voice_neg.append((s, q))

    face_pos: list[tuple[float, float]] = []
    face_neg: list[tuple[float, float]] = []
    for p in sorted((args.data / "face" / "genuine").glob("*.jpg")):
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if r.score is None:
            continue
        face_pos.append((float(r.score), float(r.quality)))
    for split in ("attack_blur", "attack_side", "attack_replay_screen"):
        for p in sorted((args.data / "face" / split).glob("*.jpg")):
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            fm.inject_bgr(bgr)
            r = fm.capture_and_score()
            s = float(r.score) if r.score is not None else 0.0
            q = float(r.quality) if r.quality is not None else 0.2
            face_neg.append((s, q))

    if not voice_pos or not face_pos:
        raise SystemExit("Need genuine voice and face scores for trust fusion")

    xs: list[np.ndarray] = []
    ys: list[int] = []

    # Positive: genuine voice × genuine face (subsample)
    pos_pairs = list(itertools.product(voice_pos, face_pos))
    rng = np.random.default_rng(args.seed)
    if len(pos_pairs) > args.max_pairs // 2:
        idx = rng.choice(len(pos_pairs), size=args.max_pairs // 2, replace=False)
        pos_pairs = [pos_pairs[i] for i in idx]
    for (vs, vq), (fs, fq) in pos_pairs:
        xs.append(_row(vs, fs, None, vq, fq))
        ys.append(1)

    # Negatives: any attack modality present
    neg_combos: list[tuple] = []
    for vn in voice_neg:
        for fp in face_pos[:5]:
            neg_combos.append((vn, fp, 0))
        for fn in face_neg:
            neg_combos.append((vn, fn, 0))
    for vp in voice_pos[:5]:
        for fn in face_neg:
            neg_combos.append((vp, fn, 0))
    # Single-modality attack rows
    for vn in voice_neg:
        neg_combos.append((vn, None, 0))
    for fn in face_neg:
        neg_combos.append((None, fn, 0))

    if len(neg_combos) > args.max_pairs // 2:
        idx = rng.choice(len(neg_combos), size=args.max_pairs // 2, replace=False)
        neg_combos = [neg_combos[i] for i in idx]
    for item in neg_combos:
        vn, fn, _ = item
        vs = vq = fs = fq = None
        if vn is not None:
            vs, vq = vn
        if fn is not None:
            fs, fq = fn
        xs.append(
            _row(
                vs,
                fs,
                None,
                float(vq or 0.0),
                float(fq or 0.0),
            )
        )
        ys.append(0)

    X = np.stack(xs)
    y = np.asarray(ys, dtype=np.int32)
    print(f"trust fusion: n={len(y)} pos={int(y.sum())} neg={int((1 - y).sum())}")

    clf, meta = train_logreg_loo(X, y, seed=args.seed, max_gap=0.12)
    out_onnx = args.store / "trust_fusion.onnx"
    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    meta.update(
        {
            "feature_keys": list(FEATURE_KEYS),
            "onnx": str(out_onnx),
            "n_voice_pos": len(voice_pos),
            "n_voice_neg": len(voice_neg),
            "n_face_pos": len(face_pos),
            "n_face_neg": len(face_neg),
            "note": "Trust fusion logreg from labeled multimodal score outcomes (Stage 2 / Phase 4)",
        }
    )
    write_json(args.store / "trust_fusion.json", meta)
    print(f"Wrote {out_onnx}")
    print(f"LOO AUC={meta['loo_auc']} gap={meta['gap']}")


if __name__ == "__main__":
    main()
