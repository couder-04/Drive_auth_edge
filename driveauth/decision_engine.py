"""Core authentication pipeline — Voice → Face → Finger ladder → Accept / Reject."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from driveauth import config
from driveauth.escalation import EscalationPolicy
from driveauth.fraud_state import FraudStateMachine
from driveauth.fusion import ConfidenceScorer, TrustFusion
from driveauth.ood_detector import OODDetector
from driveauth.policy_engine import PolicyEngine, classify_tier
from driveauth.quality_gate import QualityGate, score_face, score_finger
from driveauth.risk_model import RiskModel
from driveauth.types import Decision, DriveAuthResult, ModalityResult, RiskContext

logger = logging.getLogger("driveauth.decision")

# Parallel probe join budget; timed-out modalities fall back to unavailable
# (fail-closed for that sensor). Monkeypatchable in Phase 5 timeout tests.
CAPTURE_JOIN_TIMEOUT_S = 6.0


@dataclass
class MatcherBundle:
    voice: Any
    face: Any
    finger: Any
    behavioral: Any
    fingerprint_available: bool = True


class DecisionEngine:
    """
    Runs the DriveAuth scoring pipeline. Stateless per call except for shared
    risk-context, fraud-state, and profile held by the parent :class:`DriveAuth`
    API.
    """

    def __init__(
        self,
        *,
        matchers: MatcherBundle,
        quality: QualityGate,
        ood: OODDetector,
        risk: RiskModel,
        trust: TrustFusion,
        confidence: ConfidenceScorer,
        policy: PolicyEngine,
        fraud: FraudStateMachine,
        risk_ctx: RiskContext,
        ctx_lock: threading.Lock,
        escalation: EscalationPolicy | None = None,
        profile: Any = None,
        driver_id: str = "",
    ):
        self._m = matchers
        self._q = quality
        self._ood = ood
        self._risk = risk
        self._trust = trust
        self._conf = confidence
        self._policy = policy
        self._fraud = fraud
        self._risk_ctx = risk_ctx
        self._ctx_lock = ctx_lock
        self._escalation = escalation or EscalationPolicy()
        self._profile = profile
        self._driver_id = driver_id

    def _build_risk_ctx(
        self,
        *,
        amount: float = 0.0,
        beneficiary: str = "",
        action: str = "",
        currency: str = "INR",
        channel: str = "voice",
        beneficiary_known: bool = False,
    ) -> RiskContext:
        with self._ctx_lock:
            ctx = RiskContext(**vars(self._risk_ctx))
        ctx.amount = amount
        ctx.beneficiary = beneficiary
        ctx.action = action
        ctx.currency = currency
        ctx.channel = channel
        ctx.beneficiary_known = beneficiary_known
        try:
            beh = self._m.behavioral.get_score()
        except Exception as exc:
            logger.error("DecisionEngine: behavioral.get_score failed: %s", exc)
            beh = ModalityResult(None, False, available=False)
        ctx.behavioral_available = bool(getattr(beh, "available", True))
        # Behavioral failures must never inflate trust/risk-as-safe.
        ctx.behavioral_score = (
            beh.score if (beh.available and beh.score is not None) else None
        )
        ctx.time_hour = float(time.localtime().tm_hour)
        if self._profile is not None:
            ctx = self._profile.apply_to_context(ctx)
        return ctx

    def _probe_one(
        self,
        name: str,
        audio_np: np.ndarray | None,
        qflags,
    ) -> ModalityResult:
        """Capture + quality-gate a single modality (skip-on-bad-quality)."""
        try:
            if name == "voice":
                if audio_np is None:
                    return ModalityResult(None, False, available=False)
                if not qflags.voice_ok:
                    return ModalityResult(
                        None, False, quality=qflags.voice_q, available=True
                    )
                r = self._m.voice.score(audio_np)
                r.quality = qflags.voice_q
                return r

            if name == "face":
                return self._probe_face(qflags)

            if name == "finger":
                if not self._m.fingerprint_available:
                    return ModalityResult(None, False, available=False)
                return self._probe_finger(qflags)

            return ModalityResult(None, False, available=False)
        except Exception as exc:
            # Real-model crash / SDK fault → modality unavailable (fail closed).
            logger.error("DecisionEngine: %s probe crashed: %s", name, exc)
            return ModalityResult(None, False, available=False)

    def _probe_with_timeout(
        self,
        name: str,
        audio_np: np.ndarray | None,
        qflags,
    ) -> ModalityResult:
        """Run ``_probe_one`` under ``CAPTURE_JOIN_TIMEOUT_S`` (camera/ONNX hang)."""
        box: dict[str, ModalityResult] = {}

        def _run() -> None:
            box["r"] = self._probe_one(name, audio_np, qflags)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=CAPTURE_JOIN_TIMEOUT_S)
        if t.is_alive():
            logger.error(
                "DecisionEngine: %s probe timed out after %.2fs",
                name,
                CAPTURE_JOIN_TIMEOUT_S,
            )
            return ModalityResult(None, False, available=False)
        return box.get("r", ModalityResult(None, False, available=False))

    def _probe_face(self, qflags) -> ModalityResult:
        face = self._m.face
        if hasattr(face, "capture_frame"):
            frame = face.capture_frame()
            face_frac = getattr(face, "face_frac", None)
            frontal_ok = getattr(face, "frontal_ok", None)
            meta = getattr(face, "_last_meta", None) or {}
            if face_frac is None:
                face_frac = meta.get("face_frac")
            if frontal_ok is None:
                frontal_ok = meta.get("frontal_ok")
            ok, q, notes = score_face(frame, face_frac=face_frac, frontal_ok=frontal_ok)
            qflags.face_ok, qflags.face_q = ok, q
            qflags.notes.extend(notes)
            if frame is None:
                return ModalityResult(None, False, quality=q, available=False)
            if not ok:
                return ModalityResult(None, False, quality=q, available=True)
            if hasattr(face, "score_frame"):
                r = face.score_frame(frame)
            else:
                r = face.capture_and_score()
            if getattr(face, "last_pad_reject", False):
                qflags.face_ok = False
                qflags.notes.append("face_pad_reject")
                pad_p = getattr(face, "last_pad_score", None)
                if pad_p is not None:
                    q = min(q, float(pad_p))
                    qflags.face_q = q
                return ModalityResult(None, False, quality=q, available=True)
            r.quality = q
            return r

        r = face.capture_and_score()
        if r.score is None:
            qflags.face_ok = False
            qflags.face_q = min(qflags.face_q, 0.2)
            qflags.notes.append("face_capture_failed")
        return r

    def _probe_finger(self, qflags) -> ModalityResult:
        finger = self._m.finger
        contact = clarity = pressure = None
        if hasattr(finger, "capture_metrics"):
            contact, clarity, pressure = finger.capture_metrics()
        else:
            contact, clarity, pressure = (
                0.8,
                0.9,
                0.7,
            )  # assume OK only if no metrics API

        ok, q, notes = score_finger(contact, clarity, pressure)
        qflags.finger_ok, qflags.finger_q = ok, q
        qflags.notes.extend(notes)
        if contact is None:
            return ModalityResult(None, False, quality=q, available=False)
        if not ok:
            return ModalityResult(None, False, quality=q, available=True)
        if hasattr(finger, "score_scan"):
            r = finger.score_scan()
        else:
            r = finger.capture_and_score()
        r.quality = q
        return r

    def authenticate(
        self,
        *,
        audio_np: np.ndarray | None,
        tier_hint: str = "payment",
        amount: float = 0.0,
        beneficiary: str = "",
        action: str = "",
        currency: str = "INR",
        channel: str = "voice",
        beneficiary_known: bool = False,
        is_guest: bool = False,
        session_id: str = "",
        voice_expected: bool | None = None,
        face_expected: bool | None = None,
    ) -> DriveAuthResult:
        t_start = time.monotonic()
        explanations: list[str] = []
        sensor_gaps: list[str] = []

        risk_ctx = self._build_risk_ctx(
            amount=amount,
            beneficiary=beneficiary,
            action=action,
            currency=currency,
            channel=channel,
            beneficiary_known=beneficiary_known,
        )
        risk, risk_reasons = self._risk.score(risk_ctx)
        explanations.extend(risk_reasons)

        if not risk_ctx.behavioral_available:
            # Informational only — does not block Accept on a strong biometric ladder.
            explanations.append("behavioral_unavailable")

        profile_mature = (
            self._profile.is_mature() if self._profile is not None else True
        )
        if not profile_mature and self._profile is not None:
            explanations.append(f"profile_{self._profile.maturity_reason()}")

        tier = classify_tier(risk_ctx, is_guest=is_guest)
        rigor = self._fraud.effective_rigor(profile_mature)
        eff_state = self._fraud.effective_state(profile_mature)

        expect_voice = (
            audio_np is not None if voice_expected is None else voice_expected
        )
        # None → legacy behavior (face always on the ladder). False locks face
        # out (standalone voice-first unlock). True forces a face probe attempt.
        expect_face = True if face_expected is None else bool(face_expected)
        qflags = self._q.evaluate(voice_audio=audio_np if expect_voice else None)

        results: dict[str, ModalityResult] = {
            "voice": ModalityResult(None, False, available=False),
            "face": ModalityResult(None, False, available=False),
            "finger": ModalityResult(None, False, available=False),
        }
        available = {
            "voice": expect_voice and audio_np is not None,
            "face": expect_face,
            "finger": self._m.fingerprint_available,
        }

        ood_baseline_missing: dict[str, bool] = {}
        trust, confidence, ood_flags, eff_w = 0.0, 0.0, {}, {}
        ladder_decision: Decision | None = None
        ladder_rule: str | None = None

        if config.ESCALATION_ENABLED and not is_guest:
            plan = self._escalation.plan(
                tier=tier,
                risk=risk,
                fraud_rigor=rigor,
                profile_mature=profile_mature,
                fingerprint_available=self._m.fingerprint_available,
            )
            explanations.append(f"escalation_{plan.reason}")
            for mod, bar in plan.accept_bars.items():
                explanations.append(f"ladder_accept_bar_{mod}_{bar:.3f}")
            probed: list[str] = []

            while True:
                nxt = plan.next_modality(probed, available)
                if nxt is None:
                    break
                results[nxt] = self._probe_with_timeout(nxt, audio_np, qflags)
                probed.append(nxt)
                score = results[nxt].score
                if not results[nxt].available and score is None:
                    explanations.append(f"ladder_{nxt}_unavailable")
                trust, confidence, ood_flags, ood_baseline_missing, eff_w = self._score(
                    results, qflags, sensor_gaps
                )

                if self._escalation.should_accept(
                    plan=plan, score=score, modality=nxt
                ):
                    ladder_decision = Decision.ACCEPT
                    ladder_rule = f"{config.POLICY_VERSION}:ladder_accept_{nxt}"
                    explanations.append(
                        f"ladder_accept_{nxt}_score_{float(score):.3f}"
                    )
                    explanations.append(f"early_stop_after_{len(probed)}")
                    break

                # Low / missing score → escalate to next modality
                if score is None:
                    explanations.append(f"ladder_escalate_after_{nxt}_no_score")
                else:
                    explanations.append(
                        f"ladder_escalate_after_{nxt}_score_{float(score):.3f}"
                    )

            explanations.append(f"probed_{'+'.join(probed) if probed else 'none'}")
            if ladder_decision is None:
                ladder_decision = Decision.REJECT
                ladder_rule = f"{config.POLICY_VERSION}:ladder_reject"
                explanations.append("ladder_exhausted_reject")
        else:
            results = self._capture_all(audio_np, qflags, available)
            trust, confidence, ood_flags, ood_baseline_missing, eff_w = self._score(
                results, qflags, sensor_gaps
            )

        voice_r, face_r, finger_r = results["voice"], results["face"], results["finger"]

        if expect_voice and audio_np is not None and not qflags.voice_ok:
            explanations.append("voice_quality_rejected")
            sensor_gaps.append("voice_quality_rejected")
        if expect_voice and (
            audio_np is None or voice_r.score is None or not voice_r.confident
        ):
            sensor_gaps.append("voice_unavailable")
            if "voice_unavailable" not in explanations:
                explanations.append("voice_unavailable")
        if not face_r.available and face_r.score is None:
            explanations.append("face_unavailable")
        if any(ood_baseline_missing.values()):
            explanations.append("ood_baseline_missing")

        # Reporting scores only — decision comes from the ladder.
        trust, confidence, ood_flags, ood_baseline_missing, eff_w = self._score(
            results, qflags, sensor_gaps
        )

        n_conf = self._n_confident(results)
        decision, rule, active_thr, step_up_method = self._policy.decide(
            trust=trust,
            risk=risk,
            confidence=confidence,
            tier=tier,
            n_confident_modalities=n_conf,
            fraud_rigor=rigor,
            explanations=explanations,
            ladder_decision=ladder_decision,
            ladder_rule=ladder_rule,
        )

        result = DriveAuthResult(
            trust_score=trust,
            risk_score=risk,
            confidence_score=confidence,
            decision=decision,
            tier=tier,
            explanations=explanations,
            step_up_method=step_up_method,
            step_up_fallback="biometric_recapture_pin"
            if step_up_method == "otp_mobile"
            else None,
            policy_rule=rule,
            fraud_state=eff_state.value,
            modality_scores={
                "voice": {
                    "score": voice_r.score,
                    "conf": voice_r.confident,
                    "q": voice_r.quality,
                    "available": voice_r.available,
                },
                "face": {
                    "score": face_r.score,
                    "conf": face_r.confident,
                    "q": face_r.quality,
                    "available": face_r.available,
                },
                "finger": {
                    "score": finger_r.score,
                    "conf": finger_r.confident,
                    "q": finger_r.quality,
                    "available": finger_r.available,
                },
                "effective_weights": eff_w,
            },
            active_thresholds=active_thr,
            ood_flags=ood_flags,
            amount=amount,
            currency=currency,
            beneficiary=beneficiary,
            action=action,
            channel=channel,
            session_id=session_id,
            driver_id=self._driver_id,
        )

        self._pad_timing(t_start)
        return result

    def _capture_all(self, audio_np, qflags, available) -> dict[str, ModalityResult]:
        results: dict[str, ModalityResult] = {}
        threads: list[threading.Thread] = []

        def _voice():
            results["voice"] = (
                self._probe_one("voice", audio_np, qflags)
                if available.get("voice")
                else ModalityResult(None, False, available=False)
            )

        def _face():
            results["face"] = self._probe_one("face", audio_np, qflags)

        def _finger():
            results["finger"] = (
                self._probe_one("finger", audio_np, qflags)
                if available.get("finger")
                else ModalityResult(None, False, available=False)
            )

        for fn in (_voice, _face, _finger):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=CAPTURE_JOIN_TIMEOUT_S)
        for k in ("voice", "face", "finger"):
            results.setdefault(k, ModalityResult(None, False, available=False))
        return results

    def _score(self, results, qflags, sensor_gaps):
        voice_r, face_r, finger_r = results["voice"], results["face"], results["finger"]
        ood_eval = self._ood.evaluate(
            voice_emb=voice_r.embedding,
            face_emb=face_r.embedding,
            finger_emb=finger_r.embedding,
        )
        ood_flags = ood_eval.flags
        for name, r in (("voice", voice_r), ("face", face_r), ("finger", finger_r)):
            r.ood = ood_flags.get(name, False)
        try:
            beh = self._m.behavioral.get_score()
        except Exception as exc:
            logger.error("DecisionEngine: behavioral.get_score failed: %s", exc)
            beh = ModalityResult(None, False, available=False)
        behavioral_available = bool(getattr(beh, "available", True))
        orch_ctx = {
            "risk": 0.0,
            "behavioral_available": behavioral_available,
            "channel": "edge",
        }
        trust, eff_w = self._trust.fuse(voice_r, face_r, finger_r, orch_ctx=orch_ctx)
        confidence, conf_reasons = self._conf.score(
            voice_r,
            face_r,
            finger_r,
            qflags,
            ood_flags,
            ood_baseline_missing=ood_eval.baseline_missing,
            behavioral_available=behavioral_available,
            sensor_gaps=sensor_gaps,
        )
        for reason in conf_reasons:
            if reason not in sensor_gaps and reason not in (
                "single_modality_only",
                "modalities_disagree",
            ):
                pass
        return trust, confidence, ood_flags, ood_eval.baseline_missing, eff_w

    @staticmethod
    def _n_confident(results) -> int:
        return sum(
            1
            for r in results.values()
            if r.score is not None and r.confident and r.available
        )

    @staticmethod
    def _pad_timing(t_start: float) -> None:
        quantum = config.ESCALATION_CONSTANT_TIME_MS / 1000.0
        if quantum <= 0:
            return
        elapsed = time.monotonic() - t_start
        remaining = quantum - (elapsed % quantum)
        if remaining < quantum:
            time.sleep(remaining)
