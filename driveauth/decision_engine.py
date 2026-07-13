"""Core authentication pipeline — quality → staged matchers → scores → policy."""

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
        beh = self._m.behavioral.get_score()
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
            explanations.append("behavioral_unavailable")
            sensor_gaps.append("behavioral_unavailable")

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
        qflags = self._q.evaluate(voice_audio=audio_np if expect_voice else None)

        results: dict[str, ModalityResult] = {
            "voice": ModalityResult(None, False, available=False),
            "face": ModalityResult(None, False),
            "finger": ModalityResult(None, False),
        }
        available = {
            "voice": expect_voice and audio_np is not None,
            "face": True,
            "finger": self._m.fingerprint_available,
        }
        trust_bar = {
            "micro": config.TRUST_ACCEPT_MICRO,
            "standard": config.TRUST_ACCEPT_STD,
            "high_value": config.TRUST_ACCEPT_HIGH,
            "guest": 1.01,
        }.get(tier, config.TRUST_ACCEPT_STD) + float(rigor.get("trust_margin", 0.0))

        ood_baseline_missing: dict[str, bool] = {}
        if config.ESCALATION_ENABLED and not is_guest:
            plan = self._escalation.plan(
                tier=tier,
                risk=risk,
                fraud_rigor=rigor,
                profile_mature=profile_mature,
                fingerprint_available=self._m.fingerprint_available,
            )
            explanations.append(f"escalation_{plan.reason}")
            probed: list[str] = []
            trust, confidence, ood_flags, eff_w = 0.0, 0.0, {}, {}
            while True:
                nxt = plan.next_modality(probed, available)
                if nxt is None:
                    break
                results[nxt] = self._probe_one(nxt, audio_np, qflags)
                probed.append(nxt)
                trust, confidence, ood_flags, ood_baseline_missing, eff_w = self._score(
                    results, qflags, sensor_gaps
                )
                n_conf = self._n_confident(results)
                conf_mods = [
                    n
                    for n, r in results.items()
                    if r.score is not None and r.confident and r.available
                ]
                if self._escalation.should_stop(
                    plan=plan,
                    trust=trust,
                    confidence=confidence,
                    n_confident=n_conf,
                    trust_bar=trust_bar,
                    conf_floor=config.CONF_FLOOR,
                    confident_modalities=conf_mods,
                ):
                    explanations.append(f"early_stop_after_{len(probed)}")
                    break
            explanations.append(f"probed_{'+'.join(probed) if probed else 'none'}")
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
        if (
            self._m.fingerprint_available
            and not finger_r.available
            and finger_r.score is None
        ):
            # only note when finger was attempted / required
            pass
        if any(ood_baseline_missing.values()):
            explanations.append("ood_baseline_missing")
            sensor_gaps.append("ood_baseline_missing")

        # Recompute confidence with final sensor_gaps.
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
        )

        # Fail-closed: never silently ACCEPT when required evidence is missing.
        if decision == Decision.ACCEPT:
            block_reasons = []
            if (
                "voice_quality_rejected" in sensor_gaps
                or "voice_unavailable" in sensor_gaps
            ):
                if expect_voice:
                    block_reasons.append("fail_closed_voice")
            if "ood_baseline_missing" in sensor_gaps:
                block_reasons.append("fail_closed_ood")
            if "behavioral_unavailable" in sensor_gaps:
                block_reasons.append("fail_closed_behavioral")
            if not face_r.available and n_conf == 0:
                block_reasons.append("fail_closed_no_biometrics")
            if block_reasons:
                decision = Decision.STEP_UP_REQUIRED
                step_up_method = step_up_method or "otp_mobile"
                rule = f"{rule}+fail_closed"
                explanations.extend(block_reasons)

        if (
            not profile_mature
            and decision == Decision.ACCEPT
            and amount > config.BOOTSTRAP_AMOUNT_CAP
        ):
            decision = Decision.STEP_UP_REQUIRED
            step_up_method = "otp_mobile"
            rule = f"{rule}+bootstrap_amount_cap"
            explanations.append(
                f"bootstrap_cap_exceeded_{amount:.0f}>{config.BOOTSTRAP_AMOUNT_CAP:.0f}"
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
            t.join(timeout=6.0)
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
        beh = self._m.behavioral.get_score()
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
