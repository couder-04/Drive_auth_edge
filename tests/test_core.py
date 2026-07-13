
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


def test_policy_high_value_mandatory_stepup():
    engine = PolicyEngine()
    decision, rule, _, method = engine.decide(
        trust=0.95,
        risk=0.05,
        confidence=0.90,
        tier="high_value",
        n_confident_modalities=3,
        fraud_rigor={
            "min_modalities": 1,
            "force_step_up": False,
            "block": False,
            "trust_margin": 0.0,
        },
        explanations=[],
    )
    assert decision.value == "STEP_UP_REQUIRED"
    assert method == "otp_mobile"


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
