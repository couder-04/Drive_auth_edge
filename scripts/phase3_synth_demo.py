#!/usr/bin/env python3
"""Phase 3 demo — hybrid voice/face + manual finger/behavioral scores.

Simulates future HW modules that emit ModalityResult scores in [0, 1].

Usage:
  # happy path (high finger/behavioral)
  python scripts/phase3_synth_demo.py --store ./driveauth_store_phase2a \\
    --scores '{"finger":0.9,"behavioral":0.95}'

  # fail path (weak finger → escalation)
  python scripts/phase3_synth_demo.py --store ./driveauth_store_phase2a \\
    --scores '{"finger":0.2,"behavioral":0.95}' --scenario fail

  # or: export DRIVEAUTH_MANUAL_SCORES=./phases/manual_scores_happy.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth import DriveAuth  # noqa: E402
from driveauth.matchers.score_provider import (  # noqa: E402
    ManualScores,
    apply_manual_scores,
)
from testsupport import mature  # noqa: E402


def _load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(
            np.float32
        ) / 32768.0
        if w.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
        return audio


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3 synthetic / manual-score demo")
    parser.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument(
        "--scores",
        default="",
        help='JSON object e.g. \'{"finger":0.9,"behavioral":0.95}\' or path to .json',
    )
    parser.add_argument(
        "--scenario",
        choices=("happy", "fail", "custom"),
        default="custom",
        help="Preset score bundles (overridden by --scores if set)",
    )
    parser.add_argument("--amount", type=float, default=50.0)
    args = parser.parse_args()

    os.environ["DRIVEAUTH_USE_MOCK"] = "0"
    # Finger available so escalation can probe it when scores are injected
    os.environ["DRIVEAUTH_FINGERPRINT_AVAILABLE"] = "1"
    os.environ["DRIVEAUTH_STORE_DIR"] = args.store

    # Voice kept mid-band so escalation continues to face/finger (early-stop
    # would otherwise never probe HW stand-in scores).
    presets = {
        "happy": ManualScores(
            voice=0.55, face=0.85, finger=0.90, behavioral=0.95
        ),
        "fail": ManualScores(
            voice=0.55, face=0.70, finger=0.20, behavioral=0.95
        ),
        "custom": ManualScores(),
    }
    scores = presets[args.scenario]
    if args.scores:
        p = Path(args.scores)
        if p.is_file():
            scores = ManualScores.from_json_file(p)
        else:
            scores = ManualScores.from_json_str(args.scores)

    auth = DriveAuth.load(
        store_dir=args.store,
        enroll_dir=str(Path(args.store) / "enroll"),
        driver_id=args.driver_id,
        use_mock_matchers=False,
    )
    mature(auth)
    apply_manual_scores(auth, scores)

    enroll = sorted((ROOT / "data" / "driver1" / "voice" / "enroll").glob("*.wav"))
    if not enroll:
        raise SystemExit("No enroll wavs — record voice first")
    audio = _load_wav(enroll[0])

    print("Scenario scores:", scores)
    print("Matchers:")
    m = auth._engine._m
    print("  voice:", type(m.voice).__name__)
    print("  face:", type(m.face).__name__)
    print("  finger:", type(m.finger).__name__, "fp_avail=", m.fingerprint_available)
    print("  behavioral:", type(m.behavioral).__name__)
    print("  audio:", enroll[0].name)

    r = auth.authenticate(
        audio_np=audio,
        amount=args.amount,
        beneficiary="Mom",
        beneficiary_known=True,
        action="pay",
        currency="INR",
        channel="phase3_synth_demo",
        voice_expected=True,
    )
    print()
    print(f"Decision:   {r.decision.value}")
    print(f"Trust:      {r.trust_score:.3f}")
    print(f"Risk:       {r.risk_score:.3f}")
    print(f"Confidence: {r.confidence_score:.3f}")
    print(f"Tier:       {r.tier}")
    print(f"Rule:       {r.policy_rule}")
    print(f"Fraud:      {r.fraud_state}")
    print(f"Modalities: {json.dumps(r.modality_scores, indent=2)}")
    if r.explanations:
        print(f"Reasons:    {', '.join(r.explanations)}")


if __name__ == "__main__":
    main()
