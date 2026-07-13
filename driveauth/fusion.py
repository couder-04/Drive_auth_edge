"""Trust fusion and confidence scoring (§4.3)."""

from __future__ import annotations

import logging

import numpy as np

from driveauth import config
from driveauth.types import ModalityResult, QualityFlags, clip01

logger = logging.getLogger("driveauth.fusion")

_STATIC_W = {
    "voice": config.TRUST_W_VOICE,
    "face": config.TRUST_W_FACE,
    "finger": config.TRUST_W_FINGER,
}


class TrustFusion:
    """Biometric-only weighted fusion → Trust Score in [0, 1]."""

    def __init__(self, orchestrator=None):
        self._orch = orchestrator

    def _weights(self, ctx=None) -> dict[str, float]:
        if self._orch is not None and ctx is not None:
            try:
                w, _ = self._orch.get_weights(ctx)
                w = {
                    k: float(v)
                    for k, v in w.items()
                    if k in ("voice", "face", "finger")
                }
                s = sum(w.values())
                if s > 1e-6:
                    return {k: v / s for k, v in w.items()}
            except Exception as exc:
                logger.warning(
                    "TrustFusion: orchestrator failed (%s) — static weights", exc
                )
        return dict(_STATIC_W)

    def fuse(
        self,
        voice: ModalityResult,
        face: ModalityResult,
        finger: ModalityResult,
        orch_ctx=None,
    ) -> tuple[float, dict[str, float]]:
        base_w = self._weights(orch_ctx)
        candidates: dict[str, tuple[float, float]] = {}

        def _add(name: str, res: ModalityResult) -> None:
            if res.score is not None and res.confident and res.available:
                w = base_w.get(name, 0.0) * max(res.quality, 0.05)
                candidates[name] = (res.score, w)

        _add("voice", voice)
        _add("face", face)
        _add("finger", finger)

        if not candidates:
            return 0.0, {}

        total_w = sum(w for _, w in candidates.values())
        if total_w <= 1e-9:
            return 0.0, {}

        eff: dict[str, float] = {}
        fused = 0.0
        for name, (score, w) in candidates.items():
            ew = w / total_w
            eff[name] = ew
            fused += ew * score
        return clip01(fused), eff


class ConfidenceScorer:
    """System self-consistency score — distinct from Trust."""

    @staticmethod
    def score(
        voice: ModalityResult,
        face: ModalityResult,
        finger: ModalityResult,
        quality: QualityFlags,
        ood_flags: dict[str, bool],
        *,
        ood_baseline_missing: dict[str, bool] | None = None,
        behavioral_available: bool = True,
        sensor_gaps: list[str] | None = None,
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        present = [
            r
            for r in (voice, face, finger)
            if r.score is not None and r.confident and r.available
        ]

        if len(present) >= 2:
            scores = np.array([r.score for r in present], dtype=np.float32)
            spread = float(scores.max() - scores.min())
            agreement = clip01(1.0 - spread)
            if spread > config.CONF_DISAGREE_SPREAD:
                reasons.append("modalities_disagree")
        elif len(present) == 1:
            agreement = config.CONF_SINGLE_AGREE
            reasons.append("single_modality_only")
        else:
            return 0.0, ["no_confident_modality"]

        q_vals = []
        if voice.score is not None:
            q_vals.append(quality.voice_q)
        if face.score is not None:
            q_vals.append(quality.face_q)
        if finger.score is not None:
            q_vals.append(quality.finger_q)
        quality_score = float(np.mean(q_vals)) if q_vals else 0.5
        if quality_score < config.CONF_LOW_QUALITY:
            reasons.append("low_capture_quality")

        ood_hits = sum(1 for v in ood_flags.values() if v)
        ood_penalty = clip01(ood_hits / max(len(present), 1))
        if ood_hits:
            reasons.append("out_of_distribution_input")

        missing = ood_baseline_missing or {}
        if any(missing.get(n) for n in ("voice", "face", "finger")):
            ood_penalty = max(ood_penalty, config.CONF_OOD_MISSING)
            reasons.append("ood_baseline_missing")

        if not behavioral_available:
            ood_penalty = max(ood_penalty, config.CONF_BEHAVIOR_MISSING)
            reasons.append("behavioral_unavailable")

        if sensor_gaps:
            ood_penalty = max(ood_penalty, config.CONF_SENSOR_GAP)
            reasons.extend(sensor_gaps)

        fault_penalty = config.CONF_HW_FAULT if quality.hardware_fault else 0.0
        if quality.hardware_fault:
            reasons.append("sensor_hardware_fault")

        confidence = (
            config.CONF_W_AGREE * agreement
            + config.CONF_W_QUALITY * quality_score
            + config.CONF_W_OOD * (1.0 - ood_penalty)
            - fault_penalty
        )
        return clip01(confidence), reasons
