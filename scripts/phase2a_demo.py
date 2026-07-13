#!/usr/bin/env python3
"""Phase 2a — run auth with pretrained (hybrid) matchers.

Usage:
  DRIVEAUTH_USE_MOCK=0 python scripts/phase2a_demo.py --store ./driveauth_store_phase2a
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth import DriveAuth  # noqa: E402
from driveauth.matchers.face import FaceMatcher  # noqa: E402
from driveauth.matchers.mock import MockVoiceMatcher  # noqa: E402
from testsupport import good_audio, mature  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2a demo")
    parser.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument("--face-image", default="", help="Optional JPG/PNG to inject")
    parser.add_argument("--amount", type=float, default=50.0)
    parser.add_argument("--bench", type=int, default=0, help="If >0, run N timed auths")
    args = parser.parse_args()

    os.environ["DRIVEAUTH_USE_MOCK"] = "0"
    os.environ["DRIVEAUTH_FINGERPRINT_AVAILABLE"] = "0"
    os.environ["DRIVEAUTH_STORE_DIR"] = args.store

    auth = DriveAuth.load(
        store_dir=args.store,
        enroll_dir=str(Path(args.store) / "enroll"),
        driver_id=args.driver_id,
        use_mock_matchers=False,
    )
    mature(auth)

    voice = auth._engine._m.voice
    face = auth._engine._m.face
    print("Matchers:")
    print("  voice:", type(voice).__name__, "ready=", getattr(voice, "ready", "mock"))
    print("  face:", type(face).__name__, "ready=", getattr(face, "ready", "mock"))
    print("  finger:", type(auth._engine._m.finger).__name__)
    print("  behavioral:", type(auth._engine._m.behavioral).__name__)

    if isinstance(face, FaceMatcher) and args.face_image:
        import cv2

        bgr = cv2.imread(args.face_image)
        if bgr is None:
            raise SystemExit(f"cannot read face image: {args.face_image}")
        face.inject_bgr(bgr)
        print("  injected face image:", args.face_image)

    audio = good_audio(seconds=2.0)
    # Prefer a real enroll wav if present
    enroll_wavs = sorted((ROOT / "data" / "driver1" / "voice" / "enroll").glob("*.wav"))
    if enroll_wavs and not isinstance(voice, MockVoiceMatcher):
        import wave

        with wave.open(str(enroll_wavs[0]), "rb") as w:
            frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if w.getnchannels() == 2:
                audio = audio.reshape(-1, 2).mean(axis=1)
        print("  using enroll wav:", enroll_wavs[0].name)

    def once():
        return auth.authenticate(
            audio_np=audio,
            amount=args.amount,
            beneficiary="Mom",
            beneficiary_known=True,
            action="pay",
            currency="INR",
            channel="phase2a_demo",
            voice_expected=True,
        )

    if args.bench > 0:
        times = []
        for _ in range(args.bench):
            t0 = time.perf_counter()
            once()
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        print(f"bench n={args.bench} p50={p50:.1f}ms p95={p95:.1f}ms max={times[-1]:.1f}ms")
        return

    result = once()
    print()
    print(f"Decision:   {result.decision.value}")
    print(f"Trust:      {result.trust_score:.3f}")
    print(f"Risk:       {result.risk_score:.3f}")
    print(f"Confidence: {result.confidence_score:.3f}")
    print(f"Tier:       {result.tier}")
    print(f"Rule:       {result.policy_rule}")
    print(f"Fraud:      {result.fraud_state}")
    print(f"Modalities: {result.modality_scores}")
    if result.explanations:
        print(f"Reasons:    {', '.join(result.explanations)}")


if __name__ == "__main__":
    main()
