"""
Strict biometric ladder (voice → face → stage-3).

Architecture:
  1. Probe Voice.  High match → ACCEPT.
  2. Low / missing voice → Face.  High match → ACCEPT.
  3. Still low → stage-3 lane(s):
       finger_only   — fingerprint (default, prior behavior)
       otp_only      — Bluetooth OTP to the registered paired phone
       finger_or_otp — try lanes in ``stage3_order`` (OR, not AND)
  4. Otherwise → REJECT.

Payment ``otp_mobile`` step-up (HTTP provider) is separate and unchanged.
"High" / "match OK" are per-modality score thresholds from policy
(``ladder.accept_voice`` / ``accept_face`` / ``accept_finger``).
Timing pad remains optional (constant-time mitigation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from driveauth import config

logger = logging.getLogger("driveauth.escalation")

PROBE_ORDER = ("voice", "face", "finger")
STAGE3_MODES = frozenset({"finger_only", "otp_only", "finger_or_otp"})


def _default_accept_bars() -> dict[str, float]:
    return {
        "voice": float(config.LADDER_ACCEPT_VOICE),
        "face": float(config.LADDER_ACCEPT_FACE),
        "finger": float(config.LADDER_ACCEPT_FINGER),
        # Bluetooth OTP verify is binary (score 0 or 1); use the finger bar so
        # fraud trust_margin cannot push the threshold above 1.0.
        "otp": float(config.LADDER_ACCEPT_FINGER),
    }


def _stage3_lanes(mode: str, order: tuple[str, ...]) -> tuple[str, ...]:
    if mode == "finger_only":
        return ("finger",)
    if mode == "otp_only":
        return ("otp",)
    # finger_or_otp — preserve configured order, only known lanes.
    lanes = tuple(m for m in order if m in ("finger", "otp"))
    return lanes or ("finger", "otp")


def _effective_order(mode: str, stage3: tuple[str, ...]) -> tuple[str, ...]:
    return ("voice", "face") + stage3


@dataclass
class LadderPlan:
    """Fixed probe order for one authentication call."""

    order: tuple[str, ...] = PROBE_ORDER
    accept_bar: float = 0.70
    accept_bars: dict[str, float] = field(default_factory=_default_accept_bars)
    reason: str = "voice_face_finger_ladder"
    probed: list[str] = field(default_factory=list)
    stage3_mode: str = "finger_only"
    stage3_order: tuple[str, ...] = ("finger",)

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


def face_pad_borderline_blocks_accept(
    *,
    plan: LadderPlan,
    score: float | None,
    pad_proba: float | None = None,
    pad_threshold: float | None = None,
    margin: float | None = None,
) -> bool:
    """True when face would clear its bar but face+PAD both sit in the borderline band.

    Opt-in via ``DRIVEAUTH_FACE_BORDERLINE_MARGIN`` / ``FACE_BORDERLINE_MARGIN``
    (default 0 = never blocks). Mitigation for PAD's measured off-angle FPs —
    not a fix to PAD itself. See docs/security-assumptions.md.
    """
    m = float(config.FACE_BORDERLINE_MARGIN if margin is None else margin)
    if m <= 0.0:
        return False
    if score is None or pad_proba is None or pad_threshold is None:
        return False
    if not plan.is_accept(score, modality="face"):
        return False
    try:
        face_clearance = float(score) - plan.bar_for("face")
        pad_clearance = float(pad_proba) - float(pad_threshold)
    except (TypeError, ValueError):
        return False
    if face_clearance != face_clearance or pad_clearance != pad_clearance:
        return False
    return 0.0 <= face_clearance < m and 0.0 <= pad_clearance < m


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
        stage3_mode: str | None = None,
        stage3_order: tuple[str, ...] | None = None,
    ) -> LadderPlan:
        rigor = fraud_rigor or {}
        # Fraud trust_margin raises every modality bar; never changes ladder shape.
        margin = float(rigor.get("trust_margin", 0.0))
        bars = {k: v + margin for k, v in _default_accept_bars().items()}
        # Legacy accept_bar = voice bar (most common early-stop path).
        accept_bar = bars["voice"]
        mode = (stage3_mode or config.LADDER_STAGE3_MODE).strip().lower()
        if mode not in STAGE3_MODES:
            mode = "finger_only"
        order3 = stage3_order or config.LADDER_STAGE3_ORDER
        lanes = _stage3_lanes(mode, order3)
        order = _effective_order(mode, lanes)
        if mode == "finger_only":
            reason = "voice_face_finger_ladder"
        elif mode == "otp_only":
            reason = "voice_face_otp_ladder"
        else:
            reason = "voice_face_finger_or_otp_ladder"
        return LadderPlan(
            order=order,
            accept_bar=accept_bar,
            accept_bars=bars,
            reason=reason,
            stage3_mode=mode,
            stage3_order=lanes,
        )

    @staticmethod
    def should_accept(
        *,
        plan: LadderPlan,
        score: float | None,
        modality: str | None = None,
        pad_proba: float | None = None,
        pad_threshold: float | None = None,
    ) -> bool:
        if not plan.is_accept(score, modality=modality):
            return False
        if modality == "face" and face_pad_borderline_blocks_accept(
            plan=plan,
            score=score,
            pad_proba=pad_proba,
            pad_threshold=pad_threshold,
        ):
            return False
        return True

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
        pad_proba: float | None = None,
        pad_threshold: float | None = None,
    ) -> bool:
        """
        Compatibility shim: stop only when the latest modality score clears
        the ladder accept bar (Accept).  Callers should prefer should_accept.
        """
        if score is not None:
            return EscalationPolicy.should_accept(
                plan=plan,
                score=score,
                modality=modality,
                pad_proba=pad_proba,
                pad_threshold=pad_threshold,
            )
        return False


# Back-compat alias used in docs / imports
EscalationPlan = LadderPlan
