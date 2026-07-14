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
    Hard security gates only.

    Biometric Accept / Reject is decided by the Voice → Face → Finger ladder in
    ``DecisionEngine``.  This engine only applies irreversible rejects (fraud
    lock, risk ceiling) and guest handling.
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
        if ladder_decision is not None:
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
