"""Phases 2–6 — capture, IR liveness, Hailo face, actuation, telematics."""

from __future__ import annotations

import os

import numpy as np
import pytest

from driveauth.types import Decision, DriveAuthResult, ModalityResult
from hardware.actuation import ActuationListener, NullRelay, NullSpeaker
from hardware.hailo_face import HailoFaceMatcher, _preprocess_face
from hardware.ir_capture import (
    FACE_CROP_SIZE,
    IRCameraCapture,
    MicArrayCapture,
    NumpyAudioBackend,
    NumpyFrameBackend,
    RGBCameraCapture,
    VOICE_SAMPLE_RATE,
)
from hardware.ir_liveness import (
    IRLivenessChecker,
    extract_ir_reflectance_features,
    heuristic_live_proba,
)
from hardware.telematics import (
    MockCANReader,
    MockGPSReader,
    TelematicsIngest,
    sanitize_vehicle_fields,
)
from testsupport import good_audio, make_auth, mature


# ── Phase 2: capture services ────────────────────────────────────────────────


def test_ir_capture_shape_and_dtype():
    frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
    backend = NumpyFrameBackend(frame)
    cam = IRCameraCapture(0, backend=backend)
    assert cam.start() is True
    crop = cam.capture()
    assert crop is not None
    assert crop.shape[0] == FACE_CROP_SIZE and crop.shape[1] == FACE_CROP_SIZE
    gray = cam.capture_gray()
    assert gray is not None and gray.ndim == 2
    cam.stop()
    assert cam.capture() is None


def test_rgb_capture_matches_face_crop_contract():
    frame = np.full((200, 200, 3), 120, dtype=np.uint8)
    cam = RGBCameraCapture(1, backend=NumpyFrameBackend(frame))
    assert cam.start()
    crop = cam.capture_bgr()
    assert crop is not None
    assert crop.shape[:2] == (FACE_CROP_SIZE, FACE_CROP_SIZE)
    cam.stop()


def test_mic_capture_16k_mono_float32():
    raw = np.linspace(-0.2, 0.2, VOICE_SAMPLE_RATE, dtype=np.float32)
    mic = MicArrayCapture(backend=NumpyAudioBackend(raw))
    assert mic.start()
    buf = mic.capture(seconds=1.0)
    assert buf is not None
    assert buf.dtype == np.float32
    assert buf.ndim == 1
    assert buf.size == VOICE_SAMPLE_RATE
    assert mic.sample_rate == 16_000
    mic.stop()
    assert mic.capture() is None


def test_capture_fail_closed_when_not_started():
    cam = IRCameraCapture(0, backend=NumpyFrameBackend(np.zeros((64, 64), np.uint8)))
    assert cam.capture() is None
    mic = MicArrayCapture(backend=NumpyAudioBackend(np.zeros(100, np.float32)))
    assert mic.capture() is None


# ── Phase 3: IR liveness ─────────────────────────────────────────────────────


def _synthetic_live_ir(size: int = 112) -> np.ndarray:
    rng = np.random.default_rng(0)
    base = rng.normal(110, 25, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    base += 8.0 * np.sin(xx / 3.0) * np.cos(yy / 4.0)
    return np.clip(base, 0, 255)


def _synthetic_spoof_ir(size: int = 112) -> np.ndarray:
    # Flat bright plate — screen-like IR reflection.
    return np.full((size, size), 248.0, dtype=np.float32)


def test_ir_liveness_separates_live_and_spoof():
    checker = IRLivenessChecker(threshold=0.55)
    live = checker.check(_synthetic_live_ir())
    spoof = checker.check(_synthetic_spoof_ir())
    assert live.live is True
    assert spoof.live is False
    assert live.score - spoof.score >= 0.2


def test_ir_liveness_fail_closed_on_missing():
    checker = IRLivenessChecker()
    r = checker.check(None)
    assert r.live is False
    assert r.reason == "missing_crop"


def test_ir_liveness_extension_point_classifier():
    checker = IRLivenessChecker(classifier=lambda feats: 0.99)
    assert checker.check(_synthetic_spoof_ir()).live is True


def test_face_probe_blocked_when_liveness_fails():
    from driveauth.matchers.mock import MockFaceMatcher, MockFingerMatcher, MockVoiceMatcher

    auth = make_auth()
    mature(auth)
    auth._engine._m.face = MockFaceMatcher(score=0.95)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.20)
    auth._engine._m.fingerprint_available = True
    auth._engine._ir_liveness = IRLivenessChecker(threshold=0.55)
    backend = NumpyFrameBackend(_synthetic_spoof_ir())
    capture = IRCameraCapture(0, backend=backend)
    capture.start()
    auth._engine._ir_capture = capture
    r = auth.authenticate(audio_np=good_audio(), amount=50.0, beneficiary_known=True)
    assert any("ir_liveness" in e for e in r.explanations)
    assert r.modality_scores["face"]["score"] is None
    assert r.decision == Decision.REJECT


# ── Phase 4: Hailo face matcher ──────────────────────────────────────────────


def test_hailo_face_fail_closed_without_device():
    m = HailoFaceMatcher(None, driver_embedding=np.ones(512, np.float32))
    assert m.ready is False
    r = m.capture_and_score()
    assert r.available is False and r.score is None


def test_hailo_face_modailty_contract_with_inject_infer():
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0

    def infer(blob):
        assert blob.shape[0] == 1
        out = np.zeros(512, dtype=np.float32)
        out[0] = 1.0
        return out

    m = HailoFaceMatcher("dummy.hef", emb, infer_fn=infer)
    frame = np.full((120, 120, 3), 100, dtype=np.uint8)
    m.inject_bgr(frame)
    r = m.capture_and_score()
    assert isinstance(r, ModalityResult)
    assert r.confident is True
    assert r.score is not None and 0.0 <= r.score <= 1.0
    assert r.embedding is not None and r.embedding.shape[0] == 512


def test_hailo_and_onnx_preprocess_shape():
    frame = np.zeros((150, 160, 3), dtype=np.uint8)
    blob = _preprocess_face(frame)
    assert blob.shape == (1, 3, 112, 112)


@pytest.mark.skipif(
    os.getenv("DRIVEAUTH_HAILO_HW_TEST", "0") != "1",
    reason="Hailo device test; set DRIVEAUTH_HAILO_HW_TEST=1",
)
def test_hailo_real_device_gated(tmp_path):
    m = HailoFaceMatcher.load(str(tmp_path))
    assert isinstance(m, HailoFaceMatcher)


def test_face_matcher_contract_parametrized_backends():
    """Same ModalityResult fields for mock (stand-in for onnx) and hailo inject."""
    from driveauth.matchers.mock import MockFaceMatcher

    mock = MockFaceMatcher(score=0.88)
    r1 = mock.capture_and_score()
    emb = np.ones(512, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    hailo = HailoFaceMatcher("x.hef", emb, infer_fn=lambda b: emb)
    hailo.inject_bgr(np.full((112, 112, 3), 90, dtype=np.uint8))
    r2 = hailo.capture_and_score()
    for r in (r1, r2):
        assert hasattr(r, "score") and hasattr(r, "confident")
        assert r.score is not None


# ── Phase 5: actuation ───────────────────────────────────────────────────────


def test_actuation_relay_only_closes_on_accept():
    relay = NullRelay()
    speaker = NullSpeaker()
    act = ActuationListener(relay=relay, speaker=speaker, enable_watchdog=False)
    assert act.start() is True
    assert relay.closed is False

    reject = DriveAuthResult(
        trust_score=0.1,
        risk_score=0.1,
        confidence_score=0.1,
        decision=Decision.REJECT,
    )
    act.on_result(reject)
    assert relay.closed is False
    assert speaker.last_message is not None

    accept = DriveAuthResult(
        trust_score=0.9,
        risk_score=0.1,
        confidence_score=0.9,
        decision=Decision.ACCEPT,
    )
    act.on_result(accept)
    assert relay.closed is True

    # Fresh REJECT must re-open (no caching).
    act.on_result(reject)
    assert relay.closed is False
    act.stop()
    assert relay.closed is False


def test_actuation_step_up_keeps_relay_open():
    relay = NullRelay()
    act = ActuationListener(
        relay=relay, speaker=NullSpeaker(), enable_watchdog=False
    )
    act.start()
    act.on_result(
        DriveAuthResult(
            trust_score=0.5,
            risk_score=0.2,
            confidence_score=0.5,
            decision=Decision.STEP_UP_REQUIRED,
            step_up_method="otp_mobile",
        )
    )
    assert relay.closed is False
    act.stop()


# ── Phase 6: telematics ──────────────────────────────────────────────────────


def test_sanitize_drops_nan_and_out_of_range():
    cleaned = sanitize_vehicle_fields(
        {
            "gps_lat": float("nan"),
            "gps_lon": 200.0,
            "speed_kmh": 45.0,
            "ignition_on": 1,
            "evil_key": 999,
            "gps_accuracy_m": -1,
        }
    )
    assert "gps_lat" not in cleaned
    assert "gps_lon" not in cleaned
    assert "evil_key" not in cleaned
    assert cleaned["speed_kmh"] == 45.0
    assert cleaned["ignition_on"] is True


def test_telematics_poll_updates_context():
    auth = make_auth()
    gps = MockGPSReader({"gps_lat": 12.97, "gps_lon": 77.59, "gps_accuracy_m": 8.0})
    can = MockCANReader({"speed_kmh": 32.0, "ignition_on": True})
    ingest = TelematicsIngest(auth.update_vehicle_context, gps=gps, can=can)
    applied = ingest.poll_once()
    assert applied["gps_lat"] == pytest.approx(12.97)
    assert applied["speed_kmh"] == pytest.approx(32.0)
    with auth._ctx_lock:
        assert auth._risk_ctx.gps_lat == pytest.approx(12.97)
        assert auth._risk_ctx.speed_kmh == pytest.approx(32.0)


def test_telematics_malformed_frames_do_not_crash_or_inject():
    auth = make_auth()
    with auth._ctx_lock:
        auth._risk_ctx.speed_kmh = 10.0
    gps = MockGPSReader({"gps_lat": "not-a-float", "speed_kmh": 9999})
    can = MockCANReader(None)

    class Boom:
        def read(self):
            raise RuntimeError("bus off")

    ingest = TelematicsIngest(auth.update_vehicle_context, gps=gps, can=Boom())  # type: ignore[arg-type]
    applied = ingest.poll_once()
    assert applied == {}
    with auth._ctx_lock:
        assert auth._risk_ctx.speed_kmh == 10.0


def test_heuristic_features_dim():
    feats = extract_ir_reflectance_features(_synthetic_live_ir())
    assert feats.shape == (8,)
    assert 0.0 <= heuristic_live_proba(feats) <= 1.0
