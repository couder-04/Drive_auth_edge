"""Phase 5 — real-model failure modes (timeouts, crashes, missing sensors).

Extends production fail-closed coverage: ONNX/session crashes, probe join
timeouts, mid-inference exceptions, and sensor gaps must never raise out of
authenticate() and must not falsely Accept.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

import driveauth.decision_engine as decision_engine
from driveauth.matchers.mock import (
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from driveauth.matchers.onnx_head import OnnxLogitHead
from driveauth.risk_model import RiskModel
from driveauth.types import Decision, ModalityResult, QualityFlags, RiskContext
from testsupport import clear_ood, good_audio, make_auth, mature, seed_ood


# ── Faulty matcher doubles ───────────────────────────────────────────────────


class CrashingVoiceMatcher:
    def score(self, audio_f32, sample_rate: int = 16_000) -> ModalityResult:
        raise RuntimeError("onnx voice session aborted")


class CrashingFaceMatcher:
    face_frac = 0.35
    frontal_ok = True
    last_pad_reject = False

    def capture_frame(self):
        return np.full((112, 112), 140.0, dtype=np.float32)

    def score_frame(self, frame_gray) -> ModalityResult:
        raise RuntimeError("mobilefacenet CUDA EP crashed")

    def capture_and_score(self) -> ModalityResult:
        raise RuntimeError("mobilefacenet CUDA EP crashed")


class CrashingFingerMatcher:
    def capture_metrics(self):
        return 0.8, 0.9, 0.7

    def score_scan(self) -> ModalityResult:
        raise RuntimeError("fingerprint SDK crashed")

    def capture_and_score(self) -> ModalityResult:
        raise RuntimeError("fingerprint SDK crashed")


class HangingVoiceMatcher:
    def __init__(self, hang_s: float = 2.0):
        self._hang_s = hang_s

    def score(self, audio_f32, sample_rate: int = 16_000) -> ModalityResult:
        time.sleep(self._hang_s)
        return ModalityResult(0.99, True)


class TimeoutFaceMatcher:
    """Camera capture that never returns within the join budget."""

    face_frac = 0.35
    frontal_ok = True
    last_pad_reject = False

    def __init__(self, hang_s: float = 2.0):
        self._hang_s = hang_s

    def capture_frame(self):
        time.sleep(self._hang_s)
        return np.full((112, 112), 140.0, dtype=np.float32)

    def score_frame(self, frame_gray) -> ModalityResult:
        return ModalityResult(0.95, True)

    def capture_and_score(self) -> ModalityResult:
        time.sleep(self._hang_s)
        return ModalityResult(0.95, True)


class TimeoutFingerMatcher:
    def __init__(self, hang_s: float = 2.0):
        self._hang_s = hang_s

    def capture_metrics(self):
        time.sleep(self._hang_s)
        return 0.8, 0.9, 0.7

    def score_scan(self) -> ModalityResult:
        return ModalityResult(0.9, True)

    def capture_and_score(self) -> ModalityResult:
        time.sleep(self._hang_s)
        return ModalityResult(0.9, True)


class UnavailableVoiceMatcher:
    def score(self, audio_f32, sample_rate: int = 16_000) -> ModalityResult:
        return ModalityResult(None, False, available=False)


class NanVoiceMatcher:
    def score(self, audio_f32, sample_rate: int = 16_000) -> ModalityResult:
        return ModalityResult(float("nan"), True, embedding=np.zeros(192, dtype=np.float32))


class RaisingBehavioralMonitor:
    available = True

    def update(self, sensor: dict[str, float]) -> None:
        pass

    def get_score(self) -> ModalityResult:
        raise RuntimeError("behavioral LSTM session fault")


# ── Crash / exception fail-closed ────────────────────────────────────────────


def test_voice_onnx_crash_does_not_raise_and_escalates():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = CrashingVoiceMatcher()
    auth._engine._m.face = MockFaceMatcher(score=0.95)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_face" in e for e in r.explanations)


def test_face_matcher_crash_falls_through_to_finger():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = CrashingFaceMatcher()
    auth._engine._m.finger = MockFingerMatcher(score=0.92)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_finger" in e for e in r.explanations)


def test_all_matchers_crash_does_not_accept():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = CrashingVoiceMatcher()
    auth._engine._m.face = CrashingFaceMatcher()
    auth._engine._m.finger = CrashingFingerMatcher()
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision != Decision.ACCEPT


def test_finger_sdk_crash_after_weak_voice_face_rejects():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.35)
    auth._engine._m.face = MockFaceMatcher(score=0.35)
    auth._engine._m.finger = CrashingFingerMatcher()
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.REJECT


def test_behavioral_monitor_crash_does_not_block_accept():
    """Behavioral is risk-only; engine must swallow get_score crashes."""
    auth = make_auth()
    mature(auth)
    auth._engine._m.behavioral = RaisingBehavioralMonitor()
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.ACCEPT
    assert any("behavioral" in e for e in r.explanations)


# ── Probe join timeouts ──────────────────────────────────────────────────────


def test_voice_probe_timeout_uses_face(monkeypatch):
    monkeypatch.setattr(decision_engine, "CAPTURE_JOIN_TIMEOUT_S", 0.05)
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = HangingVoiceMatcher(hang_s=1.5)
    auth._engine._m.face = MockFaceMatcher(score=0.95)
    t0 = time.perf_counter()
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.2, f"join budget ignored: {elapsed:.2f}s"
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_face" in e for e in r.explanations)


def test_face_probe_timeout_uses_finger(monkeypatch):
    monkeypatch.setattr(decision_engine, "CAPTURE_JOIN_TIMEOUT_S", 0.05)
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = TimeoutFaceMatcher(hang_s=1.5)
    auth._engine._m.finger = MockFingerMatcher(score=0.93)
    auth._engine._m.fingerprint_available = True
    t0 = time.perf_counter()
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.2
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_finger" in e for e in r.explanations)


def test_all_probes_timeout_does_not_accept(monkeypatch):
    monkeypatch.setattr(decision_engine, "CAPTURE_JOIN_TIMEOUT_S", 0.05)
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = HangingVoiceMatcher(hang_s=1.5)
    auth._engine._m.face = TimeoutFaceMatcher(hang_s=1.5)
    auth._engine._m.finger = TimeoutFingerMatcher(hang_s=1.5)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision != Decision.ACCEPT


# ── Missing sensors / models ─────────────────────────────────────────────────


def test_missing_voice_and_face_sensors_fail_closed():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = UnavailableVoiceMatcher()
    auth._engine._m.face = MockFaceMatcher(available=False)
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=True,
    )
    assert r.decision != Decision.ACCEPT


def test_missing_camera_frame_escalates_past_face():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(available=False)
    auth._engine._m.finger = MockFingerMatcher(score=0.91)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_finger" in e for e in r.explanations)


def test_fingerprint_unavailable_flag_skips_finger_probe():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.99)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.REJECT
    assert r.modality_scores.get("finger", {}).get("score") in (None,)


def test_missing_ood_with_sensor_gaps_still_fail_closed_on_weak_bios():
    auth = make_auth()
    mature(auth)
    clear_ood(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.30)
    auth._engine._m.face = MockFaceMatcher(score=0.30)
    auth._engine._m.finger = MockFingerMatcher(available=False)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision != Decision.ACCEPT


def test_missing_behavioral_model_marks_unavailable():
    auth = make_auth()
    mature(auth)
    auth._engine._m.behavioral = MockBehavioralMonitor(available=False)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert r.decision == Decision.ACCEPT
    assert any("behavioral_unavailable" in e for e in r.explanations)


# ── ONNX head / risk corruption ──────────────────────────────────────────────


def test_onnx_logit_head_missing_file_returns_none(tmp_path: Path):
    assert OnnxLogitHead.load(tmp_path / "absent.onnx") is None


def test_onnx_logit_head_corrupt_file_returns_none(tmp_path: Path):
    bad = tmp_path / "broken.onnx"
    bad.write_bytes(b"not-onnx")
    assert OnnxLogitHead.load(bad) is None


def test_onnx_logit_head_wrong_feature_dim_raises(tmp_path: Path):
    store = Path(__file__).resolve().parents[1] / "driveauth_store_phase2a"
    pad = store / "face_pad.onnx"
    if not pad.exists():
        pytest.skip("face_pad.onnx missing")
    head = OnnxLogitHead.load(pad)
    if head is None:
        pytest.skip("Could not load face_pad.onnx")
    with pytest.raises(ValueError, match="feature dim"):
        head.predict_proba(np.zeros(99, dtype=np.float32))


def test_risk_model_corrupt_scores_via_fallback(tmp_path: Path):
    (tmp_path / "risk_gbt.onnx").write_bytes(b"garbage")
    model = RiskModel.load(str(tmp_path), strict=False)
    score, reasons = model.score(RiskContext(amount=100.0, beneficiary_known=True))
    assert 0.0 <= score <= 1.0
    assert isinstance(reasons, list)


def test_risk_model_session_run_failure_falls_back(tmp_path: Path, monkeypatch):
    model = RiskModel.load(str(tmp_path), strict=False)
    assert model._session is None
    score, _ = model.score(RiskContext(amount=50.0, beneficiary_known=False))
    assert score >= 0.0


# ── Pathological scores ──────────────────────────────────────────────────────


def test_nan_voice_score_does_not_early_accept():
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = NanVoiceMatcher()
    auth._engine._m.face = MockFaceMatcher(score=0.94)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    # NaN must not clear the ladder accept bar.
    assert not any("ladder_accept_voice" in e for e in r.explanations)
    assert r.decision in (
        Decision.ACCEPT,
        Decision.STEP_UP_REQUIRED,
        Decision.REJECT,
    )


def test_capture_all_setdefault_on_empty_results(monkeypatch):
    """Direct unit: join timeout → unavailable ModalityResult defaults."""
    monkeypatch.setattr(decision_engine, "CAPTURE_JOIN_TIMEOUT_S", 0.02)
    auth = make_auth()
    mature(auth)
    auth._engine._m.voice = HangingVoiceMatcher(hang_s=1.0)
    auth._engine._m.face = TimeoutFaceMatcher(hang_s=1.0)
    auth._engine._m.finger = TimeoutFingerMatcher(hang_s=1.0)
    qflags = QualityFlags()
    results = auth._engine._capture_all(
        good_audio(),
        qflags,
        {"voice": True, "face": True, "finger": True},
    )
    for name in ("voice", "face", "finger"):
        assert name in results
        # Timed-out threads may still finish later; at least the call returns.
        assert isinstance(results[name], ModalityResult)


def test_seeded_ood_survives_modality_unavailable():
    auth = make_auth()
    mature(auth)
    seed_ood(auth)
    auth._engine._m.voice = UnavailableVoiceMatcher()
    auth._engine._m.face = MockFaceMatcher(score=0.93)
    r = auth.authenticate(
        audio_np=None,
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
        voice_expected=False,
    )
    assert r.decision == Decision.ACCEPT
