"""Production-readiness suite — P0 pipeline fixes."""

from __future__ import annotations

import time

import numpy as np

from driveauth.intent import is_payment_utterance, parse_transaction_intent
from driveauth.matchers.mock import (
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from driveauth.policy_engine import classify_tier
from driveauth.step_up_fallback import enroll_pin
from driveauth.types import Decision, RiskContext
from testsupport import (
    clear_ood,
    good_audio,
    make_auth,
    mature,
    write_beneficiaries,
)


# ── 1–3 happy / bootstrap / high-value ───────────────────────────────────────


def test_happy_path_accept():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary="Mom",
        beneficiary_known=True,
        action="pay",
        currency="INR",
        channel="voice",
    )
    assert r.decision == Decision.ACCEPT
    assert r.tier == "micro"
    assert r.amount == 50.0
    assert r.currency == "INR"
    assert r.beneficiary == "Mom"


def test_bootstrap_stepup():
    auth = make_auth()
    r = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert r.fraud_state == "bootstrap"


def test_high_value_mandatory_stepup():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=75_000.0,
        beneficiary_known=False,
        beneficiary="new_merchant",
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert r.tier == "high_value"


# ── 4–5 / 21–23 cache ────────────────────────────────────────────────────────


def test_cache_reuse():
    auth = make_auth()
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    second = auth.require_auth(amount=50.0, beneficiary_known=True, beneficiary="Mom")
    assert first.decision == Decision.ACCEPT
    assert second is first


def test_cache_invalidation_tier_upgrade():
    auth = make_auth()
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    second = auth.require_auth(amount=90_000.0, beneficiary_known=False)
    assert second is not first
    assert second.tier == "high_value"


def test_fraud_state_invalidates_cache():
    auth = make_auth()
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert first.decision == Decision.ACCEPT
    auth._bump_fraud_epoch(auth._fraud.record_soft_flag("test"))
    second = auth.require_auth(amount=50.0, beneficiary_known=True, beneficiary="Mom")
    assert second is not first


def test_session_expiration_invalidates_cache():
    auth = make_auth()
    mature(auth)
    first = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    auth._last_result_at = time.monotonic() - 999.0
    second = auth.require_auth(amount=50.0, beneficiary_known=True, beneficiary="Mom")
    assert second is not first


# ── 6 intent lowercase ───────────────────────────────────────────────────────


def test_lowercase_beneficiary_intent():
    cases = [
        ("pay raj 200", 200.0, "Raj", "pay"),
        ("pay Amit 500", 500.0, "Amit", "pay"),
        ("send 1000 to ravi", 1000.0, "Ravi", "transfer"),
        ("transfer 2500 to Neha", 2500.0, "Neha", "transfer"),
    ]
    for text, amount, bene, action in cases:
        i = parse_transaction_intent(text)
        assert i.amount == amount, text
        assert i.beneficiary == bene, text
        assert i.action == action, text


# ── 7 non-payment ────────────────────────────────────────────────────────────


def test_non_payment_utterances_bypass_auth():
    from queue import Queue

    auth = make_auth()
    mature(auth)
    write_beneficiaries(auth, ["Mom"])
    for utt in ("open navigation", "play music", "increase AC", "call mom"):
        assert not is_payment_utterance(utt)
        llm, ws = Queue(), Queue()
        out = auth.intercept(utt, good_audio(), ws, llm)
        assert out == "pass"
        msg = llm.get_nowait()
        assert msg.get("non_payment") is True
        assert ws.empty()


def test_payment_intercept_threads_amount():
    from queue import Queue

    auth = make_auth()
    mature(auth)
    write_beneficiaries(auth, ["raj", "Raj"])
    llm, ws = Queue(), Queue()
    out = auth.intercept("pay raj 200", good_audio(), ws, llm)
    assert out in ("pass", "step_up")
    entries = auth._audit.read_entries()
    assert entries
    assert entries[-1]["amount"] == 200.0
    assert entries[-1]["beneficiary"].lower() == "raj"


# ── 8–10 missing sensors ─────────────────────────────────────────────────────


def test_missing_audio_fail_closed():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=None,
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=True,
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert any("voice" in e or "fail_closed" in e for e in r.explanations)


def test_silent_audio_fail_closed():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=np.zeros(16_000, dtype=np.float32),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.STEP_UP_REQUIRED


def test_missing_face_with_no_voice_fail_closed():
    auth = make_auth()
    mature(auth)
    auth._engine._m.face = MockFaceMatcher(available=False)
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(
        audio_np=None,
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=False,
    )
    assert r.decision != Decision.ACCEPT


def test_missing_fingerprint_when_unavailable():
    auth = make_auth()
    mature(auth)
    auth._engine._m.fingerprint_available = False
    auth._engine._m.finger = MockFingerMatcher(available=False)
    r = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    # Micro + mature can still accept on voice alone.
    assert r.decision == Decision.ACCEPT


# ── 11–12 missing OOD / behavioral ───────────────────────────────────────────


def test_missing_ood_stats_fail_closed():
    auth = make_auth()
    mature(auth)
    clear_ood(auth)
    r = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert any("ood" in e for e in r.explanations)


def test_missing_behavioral_model_fail_closed():
    auth = make_auth()
    mature(auth)
    auth._engine._m.behavioral = MockBehavioralMonitor(available=False)
    r = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert any("behavioral" in e for e in r.explanations)


# ── 13–15 bad quality ────────────────────────────────────────────────────────


def test_bad_quality_voice():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=np.zeros(8_000, dtype=np.float32),  # too short + silent
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.STEP_UP_REQUIRED
    assert any("voice" in e for e in r.explanations)


def test_bad_quality_face():
    auth = make_auth()
    mature(auth)
    auth._engine._m.face = MockFaceMatcher(bad_quality=True)
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(
        audio_np=None,
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=False,
    )
    assert r.decision != Decision.ACCEPT


def test_bad_quality_fingerprint():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.4)
    auth._engine._m.face = MockFaceMatcher(score=0.4)
    auth._engine._m.finger = MockFingerMatcher(bad_quality=True)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    # Finger rejected by quality; low voice/face → reject or step-up, never silent accept on finger
    assert r.decision in (Decision.STEP_UP_REQUIRED, Decision.REJECT)
    assert r.modality_scores["finger"]["score"] is None


# ── 16–18 OTP / PIN ──────────────────────────────────────────────────────────


def test_otp_success():
    auth = make_auth()
    ch, code = auth._otp.create_local_challenge("123456")
    assert ch.delivered
    assert auth._otp.verify("123456") is True
    assert auth._otp.has_active_challenge is False


def test_otp_timeout():
    auth = make_auth()
    auth._otp.create_local_challenge("123456")
    auth._otp.expire_active()
    assert auth._otp.verify("123456") is False


def test_otp_retry_then_fail():
    auth = make_auth()
    auth._otp.create_local_challenge("123456")
    assert auth._otp.verify("000000") is False
    assert auth._otp.has_active_challenge is True
    assert auth._otp.verify("123456") is True


def test_offline_pin_fallback():
    auth = make_auth()
    assert enroll_pin(auth._store, auth.driver_id, "9876")
    auth._fallback = type(auth._fallback)(auth._store, auth.driver_id)
    mature(auth)
    passed, reasons = auth._fallback.run(
        pin="9876",
        biometric_recheck=lambda: 0.95,
    )
    assert passed is True
    assert "fallback_passed" in reasons

    passed2, _ = auth._fallback.run(pin="0000", biometric_recheck=lambda: 0.95)
    assert passed2 is False


# ── 19 audit ─────────────────────────────────────────────────────────────────


def test_audit_log_contents():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary="Mom",
        beneficiary_known=True,
        action="pay",
        currency="INR",
        channel="voice",
    )
    entries = auth._audit.read_entries()
    assert entries
    e = entries[-1]
    for key in (
        "trust_score",
        "risk_score",
        "confidence",
        "decision",
        "tier",
        "fraud_state",
        "policy_rule",
        "explanations",
        "ts",
        "session_id",
        "driver_id",
    ):
        assert key in e, key
    assert e["decision"] == r.decision.value
    assert e["session_id"]
    assert e["driver_id"] == auth.driver_id


# ── 20 maturity update ───────────────────────────────────────────────────────


def test_driver_maturity_updates_on_every_accept():
    auth = make_auth()
    mature(auth)
    before = auth._profile._p.txn_count
    auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert auth._profile._p.txn_count == before + 1


# ── 24–25 risk / tier threading ──────────────────────────────────────────────


def test_risk_model_receives_transaction_values():
    auth = make_auth()
    mature(auth)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=150.0,
        beneficiary="Starbucks",
        beneficiary_known=True,
        action="pay",
        currency="INR",
        channel="voice",
    )
    assert r.amount == 150.0
    assert r.beneficiary == "Starbucks"
    assert r.action == "pay"
    assert r.currency == "INR"
    # Known micro → low risk
    assert r.risk_score < 0.35
    assert r.tier == "micro"


def test_classify_tier_uses_real_amount_and_beneficiary():
    assert classify_tier(RiskContext(amount=150.0, beneficiary_known=True)) == "micro"
    assert (
        classify_tier(RiskContext(amount=0.0, beneficiary_known=False)) == "high_value"
    )
    assert (
        classify_tier(RiskContext(amount=75_000.0, beneficiary_known=True))
        == "high_value"
    )
    i = parse_transaction_intent("pay raj 200")
    ctx = RiskContext(
        amount=i.amount, beneficiary=i.beneficiary, beneficiary_known=True
    )
    assert classify_tier(ctx) == "micro"
