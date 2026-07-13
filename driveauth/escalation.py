"""
Staged, risk-driven modality escalation (fixes #2, #3).

Replaces the always-parallel "run all three matchers every time" capture with a
sequential probe that stops as soon as the accumulated evidence clears the tier
bar — and escalates to the next (more costly / higher-friction) modality only
when the cheaper evidence is ambiguous.

Design decisions baked in here, each tied to a review point:

  * Probe ORDER is cheapest-friction-first: voice (already captured with the
    command) → face (already-running IR/DMS frame) → finger (deliberate touch).
  * A modality that FAILS its quality gate is skipped, not matched-then-
    downweighted — cheaper and avoids a garbage score entering fusion.
  * "min_modalities" from the fraud ladder is a FLOOR on how many confident
    modalities must be collected before ACCEPT is even eligible — so early-stop
    can never drop below the rigor the fraud state demands (fix #2's explicit
    security-floor, so single-modality accept is a deliberate policy, not an
    accident of parallelism).
  * High-value tier and Bootstrap maturity force the full set regardless of how
    confident the first probe looks.
  * Timing side-channel mitigation (fix #3): the engine pads total wall-clock to
    a fixed quantum so "fast accept vs slow escalation" is not externally
    observable. Controlled by config.ESCALATION_CONSTANT_TIME.

This module decides WHICH modalities to invoke; the actual matcher calls and
fusion stay in DecisionEngine, which asks the plan what to run next.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from driveauth import config

logger = logging.getLogger("driveauth.escalation")

# Cheapest-friction-first. "voice" is free if the command was spoken; "face" is
# free if the DMS camera is already streaming; "finger" is the deliberate step.
_DEFAULT_ORDER = ("voice", "face", "finger")


@dataclass
class EscalationPlan:
    """The probe order + stopping rules for one authentication call."""

    order: tuple[str, ...]
    min_modalities: int
    mandatory_full: bool  # must probe every available modality
    mandatory_finger: bool  # finger may not be skipped
    reason: str = ""
    probed: list[str] = field(default_factory=list)

    def next_modality(
        self, already: list[str], available: dict[str, bool]
    ) -> str | None:
        for m in self.order:
            if m in already:
                continue
            if not available.get(m, False):
                continue
            return m
        return None


class EscalationPolicy:
    """Builds an EscalationPlan from tier + risk + fraud rigor + maturity."""

    def plan(
        self,
        *,
        tier: str,
        risk: float,
        fraud_rigor: dict,
        profile_mature: bool,
        fingerprint_available: bool,
    ) -> EscalationPlan:
        min_mods = int(fraud_rigor.get("min_modalities", 1))
        force_full = False
        force_finger = False
        reason = "staged"

        # High-value and immature (bootstrap) profiles always take the full set:
        # there's no "cheap accept" path when either the amount or our knowledge
        # of the driver is high-stakes.
        if tier == "high_value":
            force_full = True
            force_finger = fingerprint_available
            reason = "high_value_full_set"
        elif not profile_mature:
            force_full = True
            reason = "bootstrap_full_set"
        elif fraud_rigor.get("force_step_up", False):
            # Heightened/locked ladder: collect at least min_mods, don't early-stop
            # on a single modality.
            min_mods = max(min_mods, 2)
            reason = "fraud_ladder_min_2"
        elif risk >= config.RISK_APPROVE:
            # Elevated risk (but below hard ceiling): require corroboration.
            min_mods = max(min_mods, 2)
            reason = "elevated_risk_min_2"

        return EscalationPlan(
            order=_DEFAULT_ORDER,
            min_modalities=min_mods,
            mandatory_full=force_full,
            mandatory_finger=force_finger,
            reason=reason,
        )

    @staticmethod
    def should_stop(
        *,
        plan: EscalationPlan,
        trust: float,
        confidence: float,
        n_confident: int,
        trust_bar: float,
        conf_floor: float,
        confident_modalities: list[str] | None = None,
    ) -> bool:
        """
        True when accumulated evidence is sufficient to STOP probing early.

        Never stops before ``min_modalities`` confident results, and never stops
        at all when the plan mandates the full set. This is the concrete
        security floor that makes single-modality accept a deliberate,
        tier-gated decision rather than a side effect of stopping too soon.
        """
        if plan.mandatory_full:
            return False
        conf_mods = confident_modalities or []
        if plan.mandatory_finger and "finger" not in conf_mods:
            return False
        if n_confident < plan.min_modalities:
            return False
        return trust >= trust_bar and confidence >= conf_floor
