
from driveauth.fusion import ConfidenceScorer, TrustFusion
from driveauth.policy_engine import PolicyEngine, classify_tier
from driveauth.risk_model import RiskModel
from driveauth.types import ModalityResult, QualityFlags, RiskContext


def test_trust_fusion_biometric_only():
    fusion = TrustFusion()
    trust, weights = fusion.fuse(
        ModalityResult(0.9, True, quality=1.0),
        ModalityResult(0.85, True, quality=1.0),
        ModalityResult(None, False),
    )
    assert 0.85 <= trust <= 0.92
    assert "voice" in weights and "face" in weights
    assert "behavior" not in weights


def test_risk_monotonic_with_novel_beneficiary():
    model = RiskModel.load("/nonexistent")
    low, _ = model.score(RiskContext(amount=100.0, beneficiary_known=True))
    high, reasons = model.score(RiskContext(amount=100.0, beneficiary_known=False))
    assert high >= low
    assert "first_time_beneficiary" in reasons


def test_policy_accept_low_risk():
    engine = PolicyEngine()
    decision, rule, _, _ = engine.decide(
        trust=0.90,
        risk=0.10,
        confidence=0.80,
        tier="standard",
        n_confident_modalities=2,
        fraud_rigor={
            "min_modalities": 1,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
    )
    assert decision.value == "ACCEPT"
    assert "accept" in rule


def test_policy_rejects_high_value_voice_accept_without_stage3():
    """High-value ladder_accept_voice must not pass PolicyEngine without stage-3."""
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.95,
        risk=0.05,
        confidence=0.90,
        tier="high_value",
        n_confident_modalities=1,
        fraud_rigor={
            "min_modalities": 1,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.ACCEPT,
        ladder_rule="driveauth-1.0:ladder_accept_voice",
    )
    assert decision == Decision.REJECT
    assert "policy_stage3_reject" in rule
    assert method is None


def test_policy_honors_high_value_accept_when_stage3_verified():
    """High-value Accept is allowed only when a real stage-3 probe is attested."""
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.95,
        risk=0.05,
        confidence=0.90,
        tier="high_value",
        n_confident_modalities=2,
        fraud_rigor={
            "min_modalities": 2,
            "force_step_up": True,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.ACCEPT,
        ladder_rule="driveauth-1.0:ladder_accept_finger",
        stage3_reached=True,
        finger_is_mock=False,
    )
    assert decision == Decision.ACCEPT
    assert "ladder_accept_finger" in rule
    assert method is None


def test_policy_rejects_high_value_accept_via_mock_finger():
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, _ = engine.decide(
        trust=0.95,
        risk=0.05,
        confidence=0.90,
        tier="high_value",
        n_confident_modalities=2,
        fraud_rigor={
            "min_modalities": 2,
            "force_step_up": True,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.ACCEPT,
        ladder_rule="driveauth-1.0:ladder_accept_finger",
        stage3_reached=True,  # ladder bookkeeping lied
        finger_is_mock=True,
    )
    assert decision == Decision.REJECT
    assert "policy_stage3_reject" in rule


def test_policy_step_up_when_high_value_has_no_stage3():
    """Missing real hardware is STEP_UP (OTP), not silent Accept or silent Reject."""
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.90,
        risk=0.10,
        confidence=0.80,
        tier="high_value",
        n_confident_modalities=1,
        fraud_rigor={
            "min_modalities": 2,
            "force_step_up": True,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.REJECT,
        ladder_rule="driveauth-1.0:ladder_reject",
        stage3_reached=False,
        finger_is_mock=True,
    )
    assert decision == Decision.STEP_UP_REQUIRED
    assert "policy_stage3_step_up" in rule
    assert method == "otp_mobile"


def test_policy_fallback_high_value_without_stage3_is_step_up():
    """Escalation-disabled fused-trust shortcut cannot Accept high-value
    without a real stage-3 (OTP was never probed on that path).
    """
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.95,
        risk=0.10,
        confidence=0.90,
        tier="high_value",
        n_confident_modalities=2,
        fraud_rigor={
            "min_modalities": 1,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=None,
        stage3_reached=False,
        finger_is_mock=True,
    )
    assert decision == Decision.STEP_UP_REQUIRED
    assert "policy_fallback_stage3_step_up" in rule
    assert method == "otp_mobile"


def test_policy_rejects_accept_below_min_modalities():
    """Ladder Accept with fewer confident matches than fraud min_modalities
    is a bookkeeping lie — fail closed to Reject (not Step-Up).
    """
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.90,
        risk=0.10,
        confidence=0.85,
        tier="standard",
        n_confident_modalities=1,
        fraud_rigor={
            "min_modalities": 2,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.ACCEPT,
        ladder_rule="driveauth-1.0:ladder_accept_face",
        stage3_reached=False,
        finger_is_mock=True,
    )
    assert decision == Decision.REJECT
    assert "policy_min_modalities_reject" in rule
    assert method is None


def test_escalation_disabled_high_value_cannot_accept_on_fused_trust(monkeypatch):
    """DRIVEAUTH_ESCALATION_ENABLED=0 used to Accept high-value on fused
    trust with n_confident_modalities >= 1 and no real stage-3.
    """
    from driveauth.types import Decision
    from testsupport import good_audio, make_auth, mature

    monkeypatch.setattr("driveauth.config.ESCALATION_ENABLED", False)
    auth = make_auth()
    mature(auth)
    result = auth.authenticate(
        audio_np=good_audio(),
        amount=75_000.0,
        beneficiary_known=False,
        beneficiary="new_merchant",
    )
    assert result.tier == "high_value"
    assert result.decision != Decision.ACCEPT
    assert result.decision == Decision.STEP_UP_REQUIRED
    assert result.step_up_method == "otp_mobile"
    assert any("policy_fallback_stage3_step_up" in e for e in result.explanations)


def test_policy_honors_ladder_reject():
    from driveauth.types import Decision

    engine = PolicyEngine()
    decision, rule, _, _ = engine.decide(
        trust=0.50,
        risk=0.05,
        confidence=0.40,
        tier="standard",
        n_confident_modalities=0,
        fraud_rigor={
            "min_modalities": 1,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
        ladder_decision=Decision.REJECT,
        ladder_rule="driveauth-1.0:ladder_reject",
    )
    assert decision == Decision.REJECT
    assert "ladder_reject" in rule


def test_confidence_drops_on_disagreement():
    scorer = ConfidenceScorer()
    conf, reasons = scorer.score(
        ModalityResult(0.95, True),
        ModalityResult(0.40, True),
        ModalityResult(None, False),
        QualityFlags(),
        {"voice": False, "face": False, "finger": False},
    )
    assert "modalities_disagree" in reasons
    assert conf < 0.90


def test_classify_tier():
    assert classify_tier(RiskContext(amount=50.0, beneficiary_known=True)) == "micro"
    assert classify_tier(RiskContext(amount=100_000.0)) == "high_value"
