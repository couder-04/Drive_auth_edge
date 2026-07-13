#!/usr/bin/env python3
"""Interactive CLI demo of DriveAuth Edge with mock matchers."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np

from driveauth import DriveAuth


def _fake_audio(seconds: float = 1.5, sr: int = 16_000) -> np.ndarray:
    # Speech-like energy variation so QualityGate SNR passes (pure sine ≈ 0 dB).
    n = int(sr * seconds)
    t = np.linspace(0, seconds, n, dtype=np.float32)
    rng = np.random.default_rng(0)
    envelope = 0.05 + 0.15 * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))
    speech = envelope * np.sin(2 * np.pi * 180 * t)
    noise = 0.005 * rng.standard_normal(n).astype(np.float32)
    return (speech + noise).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description="DriveAuth Edge demo")
    parser.add_argument("--amount", type=float, default=150.0)
    parser.add_argument("--beneficiary-known", action="store_true", default=True)
    parser.add_argument(
        "--high-value", action="store_true", help="Trigger high-value tier"
    )
    parser.add_argument(
        "--reject-voice", action="store_true", help="Use low voice score"
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Keep a brand-new (immature) profile — forces STEP_UP via fraud ladder",
    )
    args = parser.parse_args()

    store = tempfile.mkdtemp(prefix="driveauth_demo_")
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    if not args.bootstrap:
        # Fresh stores are bootstrap (force_step_up). Seed maturity so the
        # default demo can show a real ACCEPT for a known micro payment.
        auth._profile.seed_mature()

    if args.reject_voice:
        from driveauth.matchers.mock import MockVoiceMatcher

        auth._engine._m.voice = MockVoiceMatcher(score=0.40)

    amount = 75_000.0 if args.high_value else args.amount
    audio = _fake_audio()

    print("DriveAuth Edge — demo run")
    print(f"  store: {store}")
    print(f"  amount: {amount}")
    print(f"  profile: {'bootstrap' if args.bootstrap else 'mature'}")
    print()

    result = auth.authenticate(
        audio_np=audio,
        amount=amount,
        beneficiary_known=args.beneficiary_known,
        beneficiary="Starbucks" if args.beneficiary_known else "unknown_merchant",
    )

    print(f"Decision:    {result.decision.value} ({result.legacy_decision})")
    print(f"Trust:       {result.trust_score:.3f}")
    print(f"Risk:        {result.risk_score:.3f}")
    print(f"Confidence:  {result.confidence_score:.3f}")
    print(f"Tier:        {result.tier}")
    print(f"Policy rule: {result.policy_rule}")
    print(f"Fraud state: {result.fraud_state}")
    if result.explanations:
        print(f"Reasons:     {', '.join(result.explanations)}")
    if result.step_up_method:
        print(f"Step-up:     {result.step_up_method}")

    audit_path = Path(store) / "audit" / "driveauth_events.jsonl"
    if audit_path.exists():
        print(f"\nAudit log:   {audit_path}")


if __name__ == "__main__":
    main()
