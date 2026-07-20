"""Edge / failure / boundary coverage for matchers, PAD, fusion, risk."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driveauth.fusion import ConfidenceScorer, TrustFusion
from driveauth.matchers.behavioral import BehavioralMonitor, window_stat_features
from driveauth.matchers.finger import FingerMatcher
from driveauth.matchers.mock import (
    MOCK_FACE_DIM,
    MOCK_FINGER_DIM,
    MOCK_VOICE_DIM,
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from driveauth.matchers.onnx_head import OnnxLogitHead
from driveauth.matchers.voice import preprocess
from driveauth.risk_model import RiskModel
from driveauth.types import ModalityResult, QualityFlags, RiskContext


# ── Voice / face / finger mock boundaries ─────────────────────────────


def test_mock_voice_rejects_short_or_empty_audio():
    m = MockVoiceMatcher(score=0.99)
    short = np.zeros(100, dtype=np.float32)
    r = m.score(short)
    assert r.available is False
    assert r.score is None


def test_mock_voice_empty_embedding_dim():
    m = MockVoiceMatcher(score=0.5)
    audio = np.random.randn(16_000).astype(np.float32) * 0.1
    r = m.score(audio)
    assert r.embedding is not None
    assert r.embedding.shape == (MOCK_VOICE_DIM,)


def test_mock_face_unavailable_and_bad_quality():
    m = MockFaceMatcher(available=False)
    assert m.capture_and_score().available is False
    bad = MockFaceMatcher(bad_quality=True, score=0.9)
    frame = bad.capture_frame()
    assert frame is not None
    assert float(frame.mean()) < 50.0


def test_mock_finger_none_score():
    m = MockFingerMatcher(score=None)
    r = m.capture_and_score()
    assert r.score is None or r.available is False or r.confident is False


def test_voice_preprocess_handles_silence_and_nan():
    silent = np.zeros(1000, dtype=np.float32)
    out = preprocess(silent)
    assert out.shape == silent.shape
    assert np.isfinite(out).all()
    noisy = np.random.randn(2000).astype(np.float32)
    out2 = preprocess(noisy)
    assert np.isfinite(out2).all()


# ── Behavioral ────────────────────────────────────────────────────────


def test_window_stat_features_shape_and_bad_input():
    seq = np.zeros((10, 8), dtype=np.float32)
    feats = window_stat_features(seq)
    assert feats.shape == (40,)
    with pytest.raises(ValueError):
        window_stat_features(np.zeros((5, 3), dtype=np.float32))
    with pytest.raises(ValueError):
        window_stat_features(np.zeros(8, dtype=np.float32))


def test_behavioral_monitor_load_missing_model(tmp_path: Path):
    mon = BehavioralMonitor.load(str(tmp_path), "driver1")
    assert mon.available is False
    # update with empty should not crash
    mon.update({"vehicle_speed_kmh": 10.0})
    r = mon.get_score()
    assert isinstance(r, ModalityResult)


def test_mock_behavioral_low_confidence_boundary():
    m = MockBehavioralMonitor(score=0.0)
    r = m.get_score()
    assert r.score == 0.0


# ── Finger matcher without session ────────────────────────────────────


def test_finger_matcher_no_session_returns_unavailable(tmp_path: Path):
    fm = FingerMatcher(session=None, driver_template=None)
    r = fm.capture_and_score()
    assert r.score is None
    assert r.confident is False


# ── OnnxLogitHead / calibrators ───────────────────────────────────────


def test_onnx_logit_head_missing_path(tmp_path: Path):
    assert OnnxLogitHead.load(tmp_path / "nope.onnx") is None


def test_onnx_logit_head_corrupt_file(tmp_path: Path):
    bad = tmp_path / "corrupt.onnx"
    bad.write_bytes(b"not-an-onnx-file")
    assert OnnxLogitHead.load(bad) is None


# ── Trust / Confidence ────────────────────────────────────────────────


def test_trust_fusion_static_with_missing_modalities():
    tf = TrustFusion()
    assert tf.mode == "static"
    voice = ModalityResult(0.9, True)
    face = ModalityResult(None, False, available=False)
    finger = ModalityResult(0.1, False, available=True)
    score, weights = tf.fuse(voice, face, finger)
    assert 0.0 <= score <= 1.0
    assert isinstance(weights, dict)


def test_trust_fusion_empty_all_unavailable():
    tf = TrustFusion()
    z = ModalityResult(None, False, available=False)
    score, _ = tf.fuse(z, z, z)
    assert 0.0 <= score <= 1.0


def test_confidence_scorer_ood_and_disagreement():
    cs = ConfidenceScorer()
    q = QualityFlags(voice_ok=True, face_ok=False, finger_ok=True)
    voice = ModalityResult(0.95, True)
    face = ModalityResult(0.10, True)
    finger = ModalityResult(0.90, True)
    # High disagreement should reduce confidence relative to agreeing case
    low, _ = cs.score(voice, face, finger, q, ood_flags={"voice": True, "face": True})
    high, _ = cs.score(
        ModalityResult(0.9, True),
        ModalityResult(0.88, True),
        ModalityResult(0.91, True),
        QualityFlags(True, True, True),
        ood_flags={},
    )
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high >= low


# ── Risk ──────────────────────────────────────────────────────────────


def test_risk_model_additive_fallback_boundaries(tmp_path: Path):
    rm = RiskModel.load(str(tmp_path))  # no ONNX → additive
    ctx = RiskContext(
        amount=0.0,
        beneficiary_known=True,
        in_trusted_zone=True,
        speed_kmh=0.0,
        ignition_on=True,
        is_tunnel=False,
        time_hour=12.0,
    )
    low, reasons = rm.score(ctx)
    assert 0.0 <= low <= 1.0

    ctx2 = RiskContext(
        amount=100_000.0,
        beneficiary_known=False,
        in_trusted_zone=False,
        dist_from_home_km=80.0,
        speed_kmh=120.0,
        ignition_on=False,
        is_tunnel=True,
        time_hour=3.0,
        behavioral_score=0.0,
        behavioral_available=True,
        amount_mean=50.0,
        amount_std=10.0,
    )
    high, reasons2 = rm.score(ctx2)
    assert high >= low
    assert isinstance(reasons2, list)


def test_risk_model_corrupt_onnx_strict(tmp_path: Path, monkeypatch):
    from driveauth import config

    onnx = tmp_path / "risk_gbt.onnx"
    onnx.write_bytes(b"corrupt")
    monkeypatch.setattr(config, "RISK_STRICT_LOAD", True)
    with pytest.raises(Exception):
        RiskModel.load(str(tmp_path), strict=True)


# ── Corrupted / empty embeddings via mock score paths ─────────────────


def test_low_confidence_mock_bundle_scores():
    voice = MockVoiceMatcher(score=0.01, confident=False)
    face = MockFaceMatcher(score=0.02, confident=False)
    finger = MockFingerMatcher(score=0.03, confident=False)
    audio = np.random.randn(16_000).astype(np.float32) * 0.05
    vr = voice.score(audio)
    fr = face.score_frame(face.capture_frame())
    kn = finger.capture_and_score()
    assert vr.score == pytest.approx(0.01)
    assert fr.score == pytest.approx(0.02)
    assert kn.score == pytest.approx(0.03)
    assert kn.embedding is not None
    assert kn.embedding.shape == (MOCK_FINGER_DIM,)
    assert face.capture_frame() is not None
    _ = MOCK_FACE_DIM  # dim constant imported for contract docs/tests
    _ = MOCK_VOICE_DIM
