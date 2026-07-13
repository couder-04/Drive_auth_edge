"""Declarative policy engine — Trust + Risk + Confidence → Decision (§8a.4)."""

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
    ) -> tuple[Decision, str, dict[str, float], str | None]:
        trust_bar = _TRUST_ACCEPT.get(tier, _TRUST_ACCEPT["standard"])
        trust_bar += float(fraud_rigor.get("trust_margin", 0.0))
        min_mods = int(fraud_rigor.get("min_modalities", 1))
        force_su = bool(fraud_rigor.get("force_step_up", False))
        blocked = bool(fraud_rigor.get("block", False))

        active = {
            "trust_accept": round(trust_bar, 3),
            "trust_reject": _TRUST_REJECT,
            "risk_low": _RISK_LOW,
            "risk_high": _RISK_HIGH,
            "conf_floor": _CONF_FLOOR,
            "min_modalities": float(min_mods),
        }

        if blocked:
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

        if trust < _TRUST_REJECT:
            explanations.append("trust_below_floor")
            return Decision.REJECT, f"{POLICY_VERSION}:trust_floor", active, None

        if n_confident_modalities < min_mods:
            explanations.append(
                f"need_{min_mods}_modalities_have_{n_confident_modalities}"
            )
            return (
                Decision.STEP_UP_REQUIRED,
                f"{POLICY_VERSION}:insufficient_modalities",
                active,
                "otp_mobile",
            )

        if tier == "high_value" or force_su:
            rule = (
                "high_value_mandatory_stepup"
                if tier == "high_value"
                else "fraud_ladder_stepup"
            )
            explanations.append(rule)
            return (
                Decision.STEP_UP_REQUIRED,
                f"{POLICY_VERSION}:{rule}",
                active,
                "otp_mobile",
            )

        if confidence < _CONF_FLOOR:
            explanations.append("low_confidence_inputs")
            return (
                Decision.STEP_UP_REQUIRED,
                f"{POLICY_VERSION}:low_confidence",
                active,
                "otp_mobile",
            )

        if trust >= trust_bar and risk <= _RISK_LOW:
            return Decision.ACCEPT, f"{POLICY_VERSION}:accept_{tier}", active, None

        explanations.append("ambiguous_trust_or_risk")
        return (
            Decision.STEP_UP_REQUIRED,
            f"{POLICY_VERSION}:ambiguous",
            active,
            "otp_mobile",
        )
