#!/usr/bin/env python3
"""Stage 2 — train voice score calibrator (frozen ECAPA + logreg).

Writes **only** under ``voices/{driver_id}/`` — never overwrites shared legacy
store-root artifacts or another driver's heads.

Usage:
  python scripts/train_voice_calibrator.py \\
    --store driveauth_store_phase2a --data data/driver1 --driver-id driver1
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
    VOICE_CALIBRATOR,
    trainer_json_path,
    trainer_onnx_path,
)
from scripts._bio_train_common import (  # noqa: E402
    export_logreg_onnx,
    load_wav,
    ort_smoke,
    train_logreg_loo,
    write_json,
)

VOICE_FEATURE_KEYS = ("cosine", "quality", "q_ok", "duration_n", "clip_frac")
ATTACKS = ("attack_replay", "attack_silent", "attack_other_speaker")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    # Always train on raw cosine
    os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"

    from driveauth.matchers.voice import VoiceMatcher
    from driveauth.quality_gate import score_voice

    vm = VoiceMatcher.load(
        str(args.store / "enroll"), args.driver_id, store_dir=str(args.store)
    )
    if not vm.ready:
        raise SystemExit("VoiceMatcher not ready — enroll first")

    xs: list[np.ndarray] = []
    ys: list[int] = []
    paths: list[str] = []

    def _add(path: Path, label: int) -> None:
        audio = load_wav(path)
        r = vm.score(audio)
        if r.score is None:
            dur = float(audio.size / 16_000) if audio is not None else 0.0
            print(
                f"WARNING: excluding {path.relative_to(args.data)} "
                f"(VoiceMatcher.score returned None; dur={dur:.3f}s, "
                f"n_samples={0 if audio is None else len(audio)})",
                flush=True,
            )
            return
        ok, q, _ = score_voice(audio)
        duration = float(audio.size / 16_000)
        clip_frac = float(np.mean(np.abs(audio) > 0.995))
        feats = np.array(
            [float(r.score), q, 1.0 if ok else 0.0, min(duration / 5.0, 1.0), clip_frac],
            dtype=np.float32,
        )
        xs.append(feats)
        ys.append(label)
        paths.append(str(path.relative_to(args.data)))

    for p in sorted((args.data / "voice" / "genuine").glob("*.wav")):
        _add(p, 1)
    for split in ATTACKS:
        for p in sorted((args.data / "voice" / split).glob("*.wav")):
            _add(p, 0)

    if len(xs) < 6:
        raise SystemExit(f"Need more labeled voice samples (got {len(xs)})")

    X = np.stack(xs)
    y = np.asarray(ys, dtype=np.int32)
    print(
        f"voice calibrator [{args.driver_id}]: n={len(y)} "
        f"pos={int(y.sum())} neg={int((1 - y).sum())}"
    )

    clf, meta = train_logreg_loo(X, y, seed=args.seed)
    out_onnx = trainer_onnx_path(args.store, args.driver_id, VOICE_CALIBRATOR)
    out_json = trainer_json_path(args.store, args.driver_id, VOICE_CALIBRATOR)
    export_logreg_onnx(clf, out_onnx, n_features=X.shape[1])
    ort_smoke(out_onnx, X.shape[1])

    meta.update(
        {
            "driver_id": args.driver_id,
            "feature_keys": list(VOICE_FEATURE_KEYS),
            "files": paths,
            "onnx": str(out_onnx),
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "note": "Frozen ECAPA + logreg score calibrator (Stage 2, per-driver)",
        }
    )
    write_json(out_json, meta)
    print(f"Wrote {out_onnx}")
    print(f"LOO AUC={meta['loo_auc']} gap={meta['gap']}")


if __name__ == "__main__":
    main()
