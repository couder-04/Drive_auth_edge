"""
Public DriveAuth API.

Drop-in replacement for Nova's ``DriveAuthGate`` with a cleaner standalone
interface. Supports mock matchers for testing and real ONNX/SpeechBrain matchers
when a biometric store is configured.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from driveauth import config
from driveauth.audit_log import AuditLog
from driveauth.decision_engine import DecisionEngine, MatcherBundle
from driveauth.escalation import EscalationPolicy
from driveauth.fraud_state import FraudState, FraudStateMachine
from driveauth.fusion import ConfidenceScorer, TrustFusion
from driveauth.intent import is_payment_utterance, parse_transaction_intent
from driveauth.matchers.mock import (
    MOCK_FACE_DIM,
    MOCK_FINGER_DIM,
    MOCK_VOICE_DIM,
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from driveauth.ood_detector import OODDetector
from driveauth.orchestrator import DynamicOrchestrator
from driveauth.policy_engine import PolicyEngine, classify_tier
from driveauth.profile_store import ProfileStore
from driveauth.quality_gate import QualityGate
from driveauth.risk_model import RiskModel
from driveauth.step_up_fallback import StepUpFallback
from driveauth.step_up_otp import OTPStepUp
from driveauth.types import Decision, DriveAuthResult, RiskContext

logger = logging.getLogger("driveauth.api")


class DriveAuth:
    """
    Vehicle biometric authorization gate with Trust/Risk separation.

    Example::

        auth = DriveAuth.load(store_dir="./store", use_mock_matchers=True)
        result = auth.authenticate(audio_np=audio, amount=150.0)
        print(result.decision, result.trust_score, result.risk_score)
    """

    def __init__(
        self,
        *,
        driver_id: str,
        store_dir: str,
        engine: DecisionEngine,
        otp: OTPStepUp,
        fallback: StepUpFallback,
        audit: AuditLog,
        fraud: FraudStateMachine,
        profile: ProfileStore | None = None,
        enabled: bool = True,
    ):
        self.driver_id = driver_id
        self._store = store_dir
        self._engine = engine
        self._otp = otp
        self._fallback = fallback
        self._audit = audit
        self._fraud = fraud
        self._profile = profile
        self._enabled = enabled
        self._pending: dict[str, Any] | None = None
        self._pending_retries = 0
        self._risk_ctx = RiskContext()
        self._ctx_lock = threading.Lock()
        self._last_result: DriveAuthResult | None = None
        self._last_result_at: float = 0.0
        self._cache_fraud_epoch: int = 0
        self._cache_profile_epoch: int = 0
        self._fraud_epoch: int = 0
        self._session_id: str = uuid.uuid4().hex

    @classmethod
    def load(
        cls,
        store_dir: str | None = None,
        enroll_dir: str | None = None,
        driver_id: str = "driver1",
        enabled: bool = True,
        use_mock_matchers: bool = False,
    ) -> DriveAuth:
        store = Path(store_dir or os.getenv("DRIVEAUTH_STORE_DIR", "./driveauth_store"))
        store.mkdir(parents=True, exist_ok=True)

        # Phase D — optional signed-manifest integrity (fail closed when enabled).
        from driveauth.integrity import verify_store_integrity

        verify_store_integrity(store)

        if use_mock_matchers or os.getenv("DRIVEAUTH_USE_MOCK", "0") == "1":
            matchers = MatcherBundle(
                voice=MockVoiceMatcher(),
                face=MockFaceMatcher(),
                finger=MockFingerMatcher(),
                behavioral=MockBehavioralMonitor(),
                fingerprint_available=config.FINGERPRINT_AVAILABLE,
            )
            # Mock embeddings are zeros — seed matching OOD baselines so demos
            # can ACCEPT without fail-closed OOD blocking every call.
            ood = OODDetector.seed_baselines(
                str(store),
                driver_id,
                voice_dim=MOCK_VOICE_DIM,
                face_dim=MOCK_FACE_DIM,
                finger_dim=MOCK_FINGER_DIM,
            )
        else:
            from driveauth.matchers.behavioral import BehavioralMonitor
            from driveauth.matchers.face import FaceMatcher
            from driveauth.matchers.finger import FingerMatcher
            from driveauth.matchers.voice import VoiceMatcher

            enroll = enroll_dir or os.getenv(
                "DRIVEAUTH_ENROLL_DIR", str(store / "enroll")
            )
            # Phase 2a hybrid: use real matchers when ready, otherwise mock that
            # modality so the rest of the pipeline still runs on Mac/Thor.
            voice = VoiceMatcher.load(enroll, driver_id, store_dir=str(store))
            if not voice.ready:
                logger.warning("DriveAuth: voice not ready — using mock voice")
                voice = MockVoiceMatcher()

            face = FaceMatcher.load(str(store), driver_id)
            if config.FACE_BACKEND == "hailo":
                try:
                    from hardware.hailo_face import HailoFaceMatcher

                    hailo_face = HailoFaceMatcher.load(str(store), driver_id)
                    if hailo_face.ready:
                        face = hailo_face
                        logger.info("DriveAuth: using HailoFaceMatcher")
                    else:
                        logger.warning(
                            "DriveAuth: Hailo backend requested but not ready — ONNX/mock face"
                        )
                except Exception as exc:
                    logger.warning("DriveAuth: Hailo face load failed (%s)", exc)
            if not getattr(face, "ready", True):
                logger.warning("DriveAuth: face not ready — using mock face")
                face = MockFaceMatcher()

            finger_path = Path(store) / "fingernet_lite_int8.onnx"
            if finger_path.exists() and config.FINGERPRINT_AVAILABLE:
                finger = FingerMatcher.load(str(store), driver_id)
            else:
                logger.info("DriveAuth: fingerprint model/HW absent — mock finger")
                finger = MockFingerMatcher()

            behavioral = BehavioralMonitor.load(str(store), driver_id)
            if not getattr(behavioral, "available", False):
                logger.info("DriveAuth: behavioral model absent — mock behavioural")
                behavioral = MockBehavioralMonitor()

            matchers = MatcherBundle(
                voice=voice,
                face=face,
                finger=finger,
                behavioral=behavioral,
                fingerprint_available=config.FINGERPRINT_AVAILABLE
                and not isinstance(finger, MockFingerMatcher),
            )
            # Load existing OOD baselines. Never reseed on every load — that was
            # wiping enrolled 512-d face stats with the old default 128-d zeros.
            ood_dir = store / "ood_stats"
            have_ood = (ood_dir / f"voice_{driver_id}.npz").exists() or (
                ood_dir / f"face_{driver_id}.npz"
            ).exists()
            if have_ood:
                ood = OODDetector.load(str(store), driver_id)
            else:
                v_dim = (
                    int(voice._emb.shape[0])
                    if getattr(voice, "_emb", None) is not None
                    else 192
                )
                f_dim = (
                    int(face._emb.shape[0])
                    if getattr(face, "_emb", None) is not None
                    else 512
                )
                ood = OODDetector.seed_baselines(
                    str(store),
                    driver_id,
                    voice_dim=v_dim,
                    face_dim=f_dim,
                    finger_dim=64,
                )

        orchestrator = None
        try:
            orchestrator = DynamicOrchestrator.load(str(store))
        except Exception as exc:
            logger.info("DriveAuth: orchestrator unavailable (%s)", exc)

        key_path = store / ".bio_key"
        if not key_path.exists():
            try:
                from cryptography.fernet import Fernet  # type: ignore

                key_path.write_bytes(Fernet.generate_key())
            except Exception as exc:
                logger.warning("DriveAuth: key gen failed (%s)", exc)

        fraud = FraudStateMachine(store / "fraud" / "ladder.json", driver_id)
        profile = ProfileStore(store / "profiles" / f"{driver_id}.json", driver_id)
        risk_ctx = RiskContext()
        ctx_lock = threading.Lock()

        engine = DecisionEngine(
            matchers=matchers,
            quality=QualityGate(),
            ood=ood,
            risk=RiskModel.load(str(store)),
            trust=TrustFusion.load(str(store), orchestrator=orchestrator),
            confidence=ConfidenceScorer(),
            policy=PolicyEngine(),
            fraud=fraud,
            risk_ctx=risk_ctx,
            ctx_lock=ctx_lock,
            escalation=EscalationPolicy(),
            profile=profile,
            driver_id=driver_id,
        )

        auth = cls(
            driver_id=driver_id,
            store_dir=str(store),
            engine=engine,
            otp=OTPStepUp(),
            fallback=StepUpFallback(str(store), driver_id),
            audit=AuditLog(store / "audit" / "driveauth_events.jsonl"),
            fraud=fraud,
            profile=profile,
            enabled=enabled,
        )
        auth._risk_ctx = risk_ctx
        auth._ctx_lock = ctx_lock
        auth._attach_ladder_otp()
        auth._attach_ir_liveness()
        # Optional HW stand-in: DRIVEAUTH_MANUAL_SCORES=path.json or inline JSON
        try:
            from driveauth.matchers.score_provider import apply_manual_scores_from_env

            if apply_manual_scores_from_env(auth):
                logger.info("DriveAuth: applied DRIVEAUTH_MANUAL_SCORES")
        except Exception as exc:
            logger.warning("DriveAuth: manual scores skipped (%s)", exc)
        return auth

    @classmethod
    def load_gate(cls, **kwargs) -> DriveAuth:
        """Alias for ``load()`` — Nova ``DriveAuthGate.load()`` compatibility."""
        return cls.load(**kwargs)

    def new_session(self) -> str:
        self._session_id = uuid.uuid4().hex
        self.invalidate_cache()
        return self._session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def invalidate_cache(self) -> None:
        self._last_result = None
        self._last_result_at = 0.0

    def update_behavioral(self, sensor: dict[str, float]) -> None:
        self._engine._m.behavioral.update(sensor)
        with self._ctx_lock:
            if "vehicle_speed_kmh" in sensor:
                self._risk_ctx.speed_kmh = float(sensor["vehicle_speed_kmh"])
            if "ignition_on" in sensor:
                self._risk_ctx.ignition_on = bool(sensor["ignition_on"])

    def update_vehicle_context(self, **kwargs) -> None:
        with self._ctx_lock:
            for k, v in kwargs.items():
                if hasattr(self._risk_ctx, k):
                    setattr(self._risk_ctx, k, v)

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
        is_payment: bool = True,
        voice_expected: bool | None = None,
        face_expected: bool | None = None,
        session_id: str | None = None,
        audit: bool = True,
        event: str = "authenticate",
        transcript: str = "",
    ) -> DriveAuthResult:
        sid = session_id or self._session_id
        res = self._engine.authenticate(
            audio_np=audio_np,
            tier_hint=tier_hint,
            amount=amount,
            beneficiary=beneficiary,
            action=action,
            currency=currency,
            channel=channel,
            beneficiary_known=beneficiary_known,
            is_guest=is_guest,
            session_id=sid,
            voice_expected=voice_expected,
            face_expected=face_expected,
        )
        res.is_payment = is_payment
        res.session_id = sid
        res.driver_id = self.driver_id
        self._last_result = res
        self._last_result_at = time.monotonic()
        self._cache_fraud_epoch = self._fraud_epoch
        self._cache_profile_epoch = self._profile_epoch()
        if audit:
            self._post_decision(res, transcript=transcript, event=event)
        return res

    def require_auth(
        self,
        tier: str = "normal",
        *,
        amount: float = 0.0,
        beneficiary: str = "",
        action: str = "",
        currency: str = "INR",
        channel: str = "llm_tool",
        beneficiary_known: bool = False,
        allow_cached: bool = True,
    ) -> DriveAuthResult:
        """
        Second-layer gate (LLM tool-use boundary).

        Threads the parsed transaction (amount/beneficiary/action/currency/channel)
        into the full pipeline. Reuses a fresh ACCEPT within TTL when the tier
        does not increase and fraud/profile epochs are unchanged.
        """
        if allow_cached and self._can_reuse_cached(amount, beneficiary_known):
            logger.debug("require_auth: reusing fresh STT-layer decision")
            return self._last_result  # type: ignore[return-value]

        return self.authenticate(
            audio_np=None,
            tier_hint=tier if tier != "normal" else "payment",
            amount=amount,
            beneficiary=beneficiary,
            action=action,
            currency=currency,
            channel=channel,
            beneficiary_known=beneficiary_known,
            is_payment=True,
            voice_expected=False,
            event="require_auth",
        )

    def _profile_epoch(self) -> int:
        if self._profile is None:
            return 0
        return int(self._profile._p.txn_count) + int(self._profile._p.last_txn_at)

    def _can_reuse_cached(self, amount: float, beneficiary_known: bool) -> bool:
        if self._last_result is None or config.DECISION_CACHE_TTL_S <= 0:
            return False
        if (time.monotonic() - self._last_result_at) > config.DECISION_CACHE_TTL_S:
            return False
        if self._last_result.decision != Decision.ACCEPT:
            return False
        # Invalidate on fraud ladder or profile maturity changes.
        if self._fraud_epoch != self._cache_fraud_epoch:
            return False
        if self._profile_epoch() != self._cache_profile_epoch:
            return False
        probe_tier = classify_tier(
            RiskContext(amount=amount, beneficiary_known=beneficiary_known)
        )
        cached_rank = {
            "micro": 0,
            "standard": 1,
            "high_value": 2,
            "guest": 3,
            "non_payment": -1,
        }
        return cached_rank.get(probe_tier, 2) <= cached_rank.get(
            self._last_result.tier, 2
        )

    def intercept(
        self,
        transcript: str,
        audio_np: np.ndarray,
        ws_out_queue: Any,
        llm_in_queue: Any,
    ) -> str:
        """Nova STT-worker integration — returns ``pass`` | ``step_up`` | ``deny``."""
        if not self._enabled:
            llm_in_queue.put(
                {"type": "text", "text": transcript, "audio_data": audio_np.tolist()}
            )
            return "pass"

        if self._fraud.state == FraudState.LOCKED:
            self._tts_deny(
                ws_out_queue,
                "Verification is locked. Re-authenticate from the phone app.",
            )
            return "deny"

        if self._pending is not None:
            return self._handle_reauth(transcript, audio_np, ws_out_queue, llm_in_queue)

        # Non-payment commands must NEVER invoke payment auth / OTP / risk / tier.
        if not is_payment_utterance(transcript):
            llm_in_queue.put(
                {
                    "type": "text",
                    "text": transcript,
                    "audio_data": audio_np.tolist(),
                    "bio_pass": True,
                    "non_payment": True,
                }
            )
            return "pass"

        intent = parse_transaction_intent(transcript, channel="voice")
        beneficiary_known = (
            self._is_known_beneficiary(intent.beneficiary)
            if intent.beneficiary
            else False
        )
        result = self.authenticate(
            audio_np=audio_np,
            tier_hint="payment",
            amount=intent.amount,
            beneficiary=intent.beneficiary,
            action=intent.action,
            currency=intent.currency,
            channel=intent.channel,
            beneficiary_known=beneficiary_known,
            is_payment=True,
            voice_expected=True,
            event="payment_auth",
            transcript=transcript,
        )

        if result.decision == Decision.ACCEPT:
            llm_in_queue.put(
                {
                    "type": "text",
                    "text": transcript,
                    "audio_data": audio_np.tolist(),
                    "bio_score": result.trust_score,
                    "bio_pass": True,
                }
            )
            return "pass"

        if result.decision == Decision.STEP_UP_REQUIRED:
            self._pending = {
                "transcript": transcript,
                "audio_data": audio_np.tolist(),
                "is_payment": True,
                "step_up_method": result.step_up_method,
                "amount": intent.amount,
                "beneficiary": intent.beneficiary,
                "action": intent.action,
                "currency": intent.currency,
            }
            self._pending_retries = 0
            self._begin_step_up(result, ws_out_queue)
            self._bump_fraud_epoch(self._fraud.record_soft_flag("step_up"))
            return "step_up"

        self._bump_fraud_epoch(self._fraud.record_soft_flag("reject"))
        self._tts_deny(
            ws_out_queue, "I couldn't verify your identity. Please try again."
        )
        ws_out_queue.put(
            {
                "type": "security_alert",
                "reason": "driveauth_reject",
                "trust": result.trust_score,
                "risk": result.risk_score,
            }
        )
        return "deny"

    def mark_not_mine(self) -> None:
        self._bump_fraud_epoch(self._fraud.record_confirmed_fraud())

    def _bump_fraud_epoch(self, _state: FraudState | None = None) -> None:
        self._fraud_epoch += 1
        self.invalidate_cache()

    def _begin_step_up(self, result: DriveAuthResult, ws_out_queue: Any) -> None:
        if result.step_up_method == "otp_mobile":
            mobile = self._registered_mobile()
            if self._otp.send(mobile) is not None:
                ws_out_queue.put(
                    {
                        "type": "tts_speak",
                        "text": "I've sent a one-time code to your registered mobile. Please read it out.",
                    }
                )
                ws_out_queue.put({"type": "generation_start"})
                self._pending["mode"] = "otp"
                return
            ws_out_queue.put(
                {
                    "type": "tts_speak",
                    "text": "No network for OTP — verifying on-device with PIN and camera.",
                }
            )
            ws_out_queue.put({"type": "generation_start"})
            self._pending["mode"] = "fallback"
            return

        ws_out_queue.put(
            {"type": "tts_speak", "text": "Please enter your PIN to continue."}
        )
        ws_out_queue.put({"type": "generation_start"})
        self._pending["mode"] = "fallback"

    def _handle_reauth(self, transcript, audio_np, ws_out_queue, llm_in_queue) -> str:
        assert self._pending is not None
        pending = self._pending
        self._pending_retries += 1
        mode = pending.get("mode", "otp")

        passed = False
        if mode == "otp" and self._otp.has_active_challenge:
            code = "".join(ch for ch in transcript if ch.isdigit())
            passed = self._otp.verify(code)
            if not passed and not self._otp.has_active_challenge:
                # Timeout / exhausted → fall through to offline PIN.
                pending["mode"] = "fallback"
                ws_out_queue.put(
                    {
                        "type": "tts_speak",
                        "text": "OTP expired. Please enter your PIN to continue.",
                    }
                )
                ws_out_queue.put({"type": "generation_start"})
                return "step_up"
        else:
            pin = "".join(ch for ch in transcript if ch.isdigit()) or None
            passed, _ = self._fallback.run(
                pin=pin,
                biometric_recheck=lambda: (
                    self.authenticate(
                        audio_np=audio_np,
                        amount=float(pending.get("amount", 0.0)),
                        beneficiary=str(pending.get("beneficiary", "")),
                        action=str(pending.get("action", "")),
                        currency=str(pending.get("currency", "INR")),
                        beneficiary_known=True,
                        voice_expected=True,
                        audit=False,
                        is_payment=False,
                    ).trust_score
                ),
            )

        if passed:
            self._fraud.record_clean()
            llm_in_queue.put(
                {
                    "type": "text",
                    "text": pending["transcript"],
                    "audio_data": pending["audio_data"],
                    "bio_pass": True,
                }
            )
            self._pending = None
            self._pending_retries = 0
            return "pass"

        if self._pending_retries >= config.STEP_UP_RETRIES:
            self._pending = None
            self._pending_retries = 0
            state = self._fraud.record_soft_flag("step_up_exhausted")
            self._bump_fraud_epoch(state)
            msg = (
                "Too many failed attempts. Commands paused."
                if state in (FraudState.HEIGHTENED, FraudState.LOCKED)
                else "Verification failed. Request cancelled."
            )
            self._tts_deny(ws_out_queue, msg)
            return "deny"

        ws_out_queue.put(
            {"type": "tts_speak", "text": "That didn't match. Please try once more."}
        )
        ws_out_queue.put({"type": "generation_start"})
        return "step_up"

    def _post_decision(
        self, result: DriveAuthResult, *, transcript: str, event: str
    ) -> None:
        self._audit.log_decision(
            event=event,
            driver_id=self.driver_id,
            result=result,
            transcript=transcript,
            session_id=result.session_id or self._session_id,
        )
        if result.decision == Decision.ACCEPT:
            self._fraud.record_clean()
            # Every successful authentication grows maturity / rolling stats.
            if self._profile is not None:
                self._profile.record_transaction(
                    result.amount if result.is_payment else 0.0
                )
                # Home is learned only from ACCEPT-decision fixes so we're
                # confident the enrolled driver was actually there (review
                # fix #3). Bad-accuracy fixes are filtered inside
                # record_location.
                with self._ctx_lock:
                    gps_lat = self._risk_ctx.gps_lat
                    gps_lon = self._risk_ctx.gps_lon
                    gps_acc = self._risk_ctx.gps_accuracy_m
                self._profile.record_location(gps_lat, gps_lon, gps_acc)
                self._cache_profile_epoch = self._profile_epoch()

    def _is_known_beneficiary(self, name: str) -> bool:
        if not name:
            return False
        path = Path(self._store) / "beneficiaries" / f"{self.driver_id}.txt"
        try:
            if path.exists():
                known = {
                    ln.strip().lower()
                    for ln in path.read_text().splitlines()
                    if ln.strip()
                }
                return name.strip().lower() in known
        except Exception:
            pass
        return False

    def _registered_mobile(self) -> str | None:
        path = Path(self._store) / "contacts" / f"{self.driver_id}.mobile"
        if path.exists():
            return path.read_text().strip()
        return os.getenv("DRIVEAUTH_DRIVER_MOBILE", os.getenv("NOVA_DRIVER_MOBILE"))

    def _registered_bt_mac(self) -> str | None:
        """MAC registered for the driver's phone (HFP pairing reuse)."""
        path = Path(self._store) / "contacts" / f"{self.driver_id}.bt_mac"
        if path.exists():
            return path.read_text().strip()
        return os.getenv("DRIVEAUTH_DRIVER_BT_MAC", os.getenv("NOVA_DRIVER_BT_MAC"))

    def _attach_ladder_otp(self) -> None:
        """Wire a separate Bluetooth OTPStepUp for identity-ladder stage-3."""
        if config.LADDER_STAGE3_MODE == "finger_only":
            self._engine._ladder_otp = None
            return
        try:
            from hardware.bluetooth_otp import BluetoothOTPDelivery
            from hardware.ladder_otp import LadderOTPLane
            from driveauth.step_up_otp import OTPStepUp as _OTP

            delivery = BluetoothOTPDelivery(
                registered_mac_lookup=self._registered_bt_mac,
            )
            # Independent challenge state from payment ``self._otp``.
            ladder_otp_stepup = _OTP(delivery=delivery)
            self._engine._ladder_otp = LadderOTPLane(
                otp=ladder_otp_stepup,
                mobile_lookup=self._registered_mobile,
                registered_mac_lookup=self._registered_bt_mac,
            )
        except Exception as exc:
            logger.warning("DriveAuth: ladder OTP lane unavailable (%s)", exc)
            self._engine._ladder_otp = None

    def _attach_ir_liveness(self) -> None:
        """Optional IR liveness gate (``DRIVEAUTH_IR_LIVENESS_ENABLED=1``)."""
        if not config.IR_LIVENESS_ENABLED:
            self._engine._ir_liveness = None
            self._engine._ir_capture = None
            return
        try:
            from hardware.ir_capture import IRCameraCapture, NumpyFrameBackend
            from hardware.ir_liveness import IRLivenessChecker

            # Prefer live OpenCV; fall back to inject-only backend so the gate
            # fail-closes on missing frames rather than crashing import.
            capture = IRCameraCapture(config.IR_CAMERA_INDEX)
            if not capture.start():
                capture = IRCameraCapture(
                    config.IR_CAMERA_INDEX, backend=NumpyFrameBackend()
                )
                capture.start()
            self._engine._ir_capture = capture
            self._engine._ir_liveness = IRLivenessChecker(
                threshold=config.IR_LIVENESS_THRESHOLD,
                ensemble=config.IR_LIVENESS_ENSEMBLE,
            )
            logger.info(
                "DriveAuth: IR liveness enabled (thr=%.3f ensemble=%s)",
                config.IR_LIVENESS_THRESHOLD,
                config.IR_LIVENESS_ENSEMBLE,
            )
        except Exception as exc:
            logger.warning("DriveAuth: IR liveness unavailable (%s)", exc)
            self._engine._ir_liveness = None
            self._engine._ir_capture = None

    def _tts_deny(self, ws_out_queue: Any, message: str) -> None:
        ws_out_queue.put({"type": "tts_speak", "text": message})
        ws_out_queue.put({"type": "recording_stopped"})


DriveAuthGate = DriveAuth
