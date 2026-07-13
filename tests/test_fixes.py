import tempfile
import time
from pathlib import Path

from driveauth.intent import parse_transaction_intent
from driveauth.escalation import EscalationPolicy, EscalationPlan
from driveauth.profile_store import ProfileStore
from driveauth.policy_engine import classify_tier
from driveauth.types import RiskContext


def test_intent_parses_amount_and_beneficiary():
    i = parse_transaction_intent("pay Raj 200")
    assert i.amount == 200.0
    assert i.beneficiary == "Raj"
    assert i.action == "pay"


def test_intent_lowercase_names():
    i = parse_transaction_intent("pay raj 200")
    assert i.amount == 200.0
    assert i.beneficiary == "Raj"


def test_intent_amount_tiers_micro_not_highvalue():
    # The whole point of fix #1: a small known-beneficiary payment must tier as
    # micro, not fall through to high_value because amount defaulted to 0.
    i = parse_transaction_intent("transfer 150 to Mom")
    ctx = RiskContext(amount=i.amount, beneficiary_known=True)
    assert classify_tier(ctx) == "micro"


def test_intent_unknown_fails_safe_to_highvalue():
    # No parseable amount → 0.0 + unknown beneficiary → high_value (more scrutiny).
    i = parse_transaction_intent("do the thing")
    ctx = RiskContext(amount=i.amount, beneficiary_known=False)
    assert classify_tier(ctx) == "high_value"


def test_escalation_stops_early_when_bar_met():
    pol = EscalationPolicy()
    plan = EscalationPlan(
        order=("voice", "face", "finger"),
        min_modalities=1,
        mandatory_full=False,
        mandatory_finger=False,
    )
    assert (
        pol.should_stop(
            plan=plan,
            trust=0.9,
            confidence=0.9,
            n_confident=1,
            trust_bar=0.75,
            conf_floor=0.55,
        )
        is True
    )


def test_escalation_never_stops_below_min_modalities():
    pol = EscalationPolicy()
    plan = EscalationPlan(
        order=("voice", "face", "finger"),
        min_modalities=2,
        mandatory_full=False,
        mandatory_finger=False,
    )
    assert (
        pol.should_stop(
            plan=plan,
            trust=0.99,
            confidence=0.99,
            n_confident=1,
            trust_bar=0.75,
            conf_floor=0.55,
        )
        is False
    )


def test_escalation_high_value_forces_full_set():
    pol = EscalationPolicy()
    plan = pol.plan(
        tier="high_value",
        risk=0.1,
        fraud_rigor={"min_modalities": 1},
        profile_mature=True,
        fingerprint_available=True,
    )
    assert plan.mandatory_full is True


def test_profile_maturity_needs_history_and_recency():
    store = tempfile.mkdtemp()
    p = ProfileStore(Path(store) / "p.json", "driver1")
    assert p.is_mature() is False  # brand new
    p.seed_mature()
    assert p.is_mature() is True
    # Now make it stale — a long gap since last txn drops maturity again.
    p._p.last_txn_at = time.time() - 200 * 86400
    assert p.is_mature() is False


def test_profile_ood_refresh_gated():
    store = tempfile.mkdtemp()
    p = ProfileStore(Path(store) / "p.json", "driver1")
    assert p.can_refresh_ood(strong_auth_passed=False) is False
    assert p.can_refresh_ood(strong_auth_passed=True) is True


def test_profile_welford_std():
    store = tempfile.mkdtemp()
    p = ProfileStore(Path(store) / "p.json", "driver1")
    for v in (100.0, 200.0, 300.0):
        p.record_transaction(v)
    assert abs(p._p.amount_mean - 200.0) < 1e-6
    assert p._p.amount_std > 0
