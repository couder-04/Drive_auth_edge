"""
Strict biometric ladder (voice → face → finger).

Architecture:
  1. Probe Voice.  High match → ACCEPT.
  2. Low / missing voice → Face.  High match → ACCEPT.
  3. Still low → Fingerprint (last resort).  Match OK → ACCEPT.
  4. Otherwise → REJECT.

No OTP mid-ladder.  "High" / "match OK" are per-modality score thresholds
from policy (``ladder.accept_voice`` / ``accept_face`` / ``accept_finger``).
Timing pad remains optional (constant-time mitigation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from driveauth import config

logger = logging.getLogger("driveauth.escalation")

PROBE_ORDER = ("voice", "face", "finger")


def _default_accept_bars() -> dict[str, float]:
    return {
        "voice": float(config.LADDER_ACCEPT_VOICE),
        "face": float(config.LADDER_ACCEPT_FACE),
        "finger": float(config.LADDER_ACCEPT_FINGER),
    }


@dataclass
class LadderPlan:
    """Fixed probe order for one authentication call."""

    order: tuple[str, ...] = PROBE_ORDER
    accept_bar: float = 0.70
    accept_bars: dict[str, float] = field(default_factory=_default_accept_bars)
    reason: str = "voice_face_finger_ladder"
    probed: list[str] = field(default_factory=list)

    def bar_for(self, modality: str | None = None) -> float:
        if modality and modality in self.accept_bars:
            return float(self.accept_bars[modality])
        return float(self.accept_bar)

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

    def is_accept(self, score: float | None, modality: str | None = None) -> bool:
        """True when this modality's match score is high enough to ACCEPT."""
        if score is None:
            return False
        try:
            val = float(score)
        except (TypeError, ValueError):
            return False
        if val != val:  # NaN
            return False
        return val >= self.bar_for(modality)


class EscalationPolicy:
    """Builds a LadderPlan (kept name for call-site compatibility)."""

    def plan(
        self,
        *,
        tier: str = "standard",
        risk: float = 0.0,
        fraud_rigor: dict | None = None,
        profile_mature: bool = True,
        fingerprint_available: bool = True,
    ) -> LadderPlan:
        rigor = fraud_rigor or {}
        # Fraud trust_margin raises every modality bar; never changes ladder shape.
        margin = float(rigor.get("trust_margin", 0.0))
        bars = {k: v + margin for k, v in _default_accept_bars().items()}
        # Legacy accept_bar = voice bar (most common early-stop path).
        accept_bar = bars["voice"]
        return LadderPlan(
            order=PROBE_ORDER,
            accept_bar=accept_bar,
            accept_bars=bars,
            reason="voice_face_finger_ladder",
        )

    @staticmethod
    def should_accept(
        *,
        plan: LadderPlan,
        score: float | None,
        modality: str | None = None,
    ) -> bool:
        return plan.is_accept(score, modality=modality)

    @staticmethod
    def should_stop(
        *,
        plan: LadderPlan,
        trust: float,
        confidence: float,
        n_confident: int,
        trust_bar: float,
        conf_floor: float,
        confident_modalities: list[str] | None = None,
        score: float | None = None,
        modality: str | None = None,
    ) -> bool:
        """
        Compatibility shim: stop only when the latest modality score clears
        the ladder accept bar (Accept).  Callers should prefer should_accept.
        """
        if score is not None:
            return plan.is_accept(score, modality=modality)
        return False


# Back-compat alias used in docs / imports
EscalationPlan = LadderPlan
