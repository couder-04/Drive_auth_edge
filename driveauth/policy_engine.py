"""Hard gates + guest handling. Biometric Accept/Reject is the voice→face→finger ladder."""

from __future__ import annotations

import logging

from driveauth import config
from driveauth.types import Decision, RiskContext

logger = logging.getLogger("driveauth.policy")

POLICY_VERSION = config.POLICY_VERSION
_TRUST_ACCEPT = {
    "micro": config.TRUST_ACCEPT_MICRO,
    "standard": config.TRUST_ACCEPT_STD,
    "high_value": config.TRUST_ACCEPT_HIGH,
    "guest": 1.01,
}
_TRUST_REJECT = config.TRUST_REJECT
_RISK_LOW = config.RISK_APPROVE
_RISK_HIGH = config.RISK_REJECT
_CONF_FLOOR = config.CONF_FLOOR
_MICRO_MAX = config.TIER_MICRO_MAX
_HIGH_MIN = config.TIER_HIGH_MIN


def classify_tier(ctx: RiskContext, is_guest: bool = False) -> str:
    if is_guest:
        return "guest"
    if ctx.amount <= _MICRO_MAX and ctx.beneficiary_known:
        return "micro"
    if ctx.amount >= _HIGH_MIN or not ctx.beneficiary_known:
        return "high_value"
    return "standard"


class PolicyEngine:
    """
    Hard security gates plus independent stage-3 verification.

    Biometric Accept / Reject is proposed by the Voice → Face → Finger ladder in
    ``DecisionEngine``. This engine applies irreversible rejects (fraud lock,
    risk ceiling), guest PIN handling, and a second check that a forced
    stage-3 ACCEPT actually used a real (non-mock) finger or OTP probe.
    Missing real stage-3 on high-value / force_step_up becomes STEP_UP
    (otp_mobile), not silent Accept.
    """

    def decide(
        self,
        *,
        trust: float,
        risk: float,
        confidence: float,
        tier: str,
        n_confident_modalities: int,
        fraud_rigor: dict,
        explanations: list[str],
        ladder_decision: Decision | None = None,
        ladder_rule: str | None = None,
        # Fail-closed defaults: callers must pass a verified stage-3, not rely
        # on "assume true" when the ladder omitted the kwargs.
        stage3_reached: bool = False,
        finger_is_mock: bool = False,
    ) -> tuple[Decision, str, dict[str, float], str | None]:
        trust_bar = _TRUST_ACCEPT.get(tier, _TRUST_ACCEPT["standard"])
        trust_bar += float(fraud_rigor.get("trust_margin", 0.0))
        blocked = bool(fraud_rigor.get("block", False))

        active = {
            "trust_accept": round(trust_bar, 3),
            "trust_reject": _TRUST_REJECT,
            "risk_low": _RISK_LOW,
            "risk_high": _RISK_HIGH,
            "conf_floor": _CONF_FLOOR,
            "ladder_accept": float(config.LADDER_ACCEPT),
            "ladder_accept_voice": float(config.LADDER_ACCEPT_VOICE),
            "ladder_accept_face": float(config.LADDER_ACCEPT_FACE),
            "ladder_accept_finger": float(config.LADDER_ACCEPT_FINGER),
            "min_modalities": float(fraud_rigor.get("min_modalities", 1)),
        }

        if blocked:
            explanations.append("fraud_locked")
            return Decision.REJECT, f"{POLICY_VERSION}:fraud_locked", active, None

        if tier == "guest":
            explanations.append("guest_mode_requires_pin")
            return (
                Decision.STEP_UP_REQUIRED,
                f"{POLICY_VERSION}:guest_pin_required",
                active,
                "pin_card_present",
            )

        if risk >= _RISK_HIGH:
            explanations.append("risk_above_hard_ceiling")
            return Decision.REJECT, f"{POLICY_VERSION}:risk_ceiling", active, None

        # Ladder already chose ACCEPT or REJECT from biometric probes.
        # Independently verify forced stage-3 rather than trusting the ladder.
        if ladder_decision is not None:
            needs_stage3 = tier == "high_value" or bool(
                fraud_rigor.get("force_step_up")
            )
            via_mock_finger = finger_is_mock and "ladder_accept_finger" in (
                ladder_rule or ""
            )
            if (
                ladder_decision == Decision.ACCEPT
                and needs_stage3
                and (not stage3_reached or via_mock_finger)
            ):
                # Ladder claims accept but policy's own check disagrees — fail closed.
                explanations.append("policy_stage3_verification_failed")
                return (
                    Decision.REJECT,
                    f"{POLICY_VERSION}:policy_stage3_reject",
                    active,
                    None,
                )
            if (
                ladder_decision == Decision.REJECT
                and needs_stage3
                and not stage3_reached
            ):
                # No real stage-3 available — PIN/OTP fallback, not silent Reject.
                explanations.append("policy_stage3_step_up")
                return (
                    Decision.STEP_UP_REQUIRED,
                    f"{POLICY_VERSION}:policy_stage3_step_up",
                    active,
                    "otp_mobile",
                )
            rule = ladder_rule or f"{POLICY_VERSION}:ladder"
            return ladder_decision, rule, active, None

        # Fallback when ladder disabled: Accept on strong fused trust, else Reject.
        if (
            trust >= trust_bar
            and risk <= _RISK_LOW
            and confidence >= _CONF_FLOOR
            and n_confident_modalities >= 1
        ):
            return Decision.ACCEPT, f"{POLICY_VERSION}:accept_{tier}", active, None

        explanations.append("biometric_ladder_reject")
        return Decision.REJECT, f"{POLICY_VERSION}:reject", active, None
