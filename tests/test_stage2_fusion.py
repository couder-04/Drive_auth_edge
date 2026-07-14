"""Stage 2 — trust fusion logreg path + face PAD gate."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driveauth.fusion import TrustFusion
from driveauth.types import ModalityResult

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "driveauth_store_phase2a"


def test_trust_fusion_static_when_no_onnx(tmp_path):
    fusion = TrustFusion.load(tmp_path, orchestrator=None)
    assert fusion.mode == "static"
    voice = ModalityResult(score=0.9, confident=True, quality=1.0)
    face = ModalityResult(score=0.6, confident=True, quality=1.0)
    finger = ModalityResult(score=None, confident=False, available=False)
    trust, eff = fusion.fuse(voice, face, finger)
    expected = (0.3 / 0.7) * 0.9 + (0.4 / 0.7) * 0.6
    assert abs(trust - expected) < 1e-6
    assert fusion.last_mode == "static"


@pytest.mark.skipif(
    not (STORE / "trust_fusion.onnx").exists(),
    reason="trust_fusion.onnx not trained",
)
def test_trust_fusion_logreg_not_static_only():
    fusion = TrustFusion.load(STORE, orchestrator=None)
    assert fusion.mode == "logreg"
    voice = ModalityResult(score=0.9, confident=True, quality=1.0)
    face = ModalityResult(score=0.6, confident=True, quality=1.0)
    finger = ModalityResult(score=None, confident=False, available=False)
    trust_logreg, _ = fusion.fuse(voice, face, finger)
    assert fusion.last_mode == "logreg"

    static = TrustFusion(orchestrator=None, logreg=None)
    trust_static, _ = static.fuse(voice, face, finger)
    assert abs(trust_logreg - trust_static) > 1e-4


@pytest.mark.skipif(
    not (STORE / "face_pad.onnx").exists(),
    reason="face_pad.onnx not trained",
)
def test_face_pad_rejects_blur_attack():
    import cv2

    from driveauth.matchers.face import FaceMatcher

    data = ROOT / "data" / "driver1" / "face" / "attack_blur"
    images = sorted(data.glob("*.jpg"))
    if not images:
        pytest.skip("no blur attacks")
    fm = FaceMatcher.load(str(STORE), "driver1")
    if not fm.has_pad:
        pytest.skip("PAD not loaded")
    rejected = 0
    for p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if r.score is None and fm.last_pad_reject:
            rejected += 1
    assert rejected >= max(1, len(images) // 2)


@pytest.mark.skipif(
    not (STORE / "voice_calibrator.onnx").exists(),
    reason="voice_calibrator.onnx not trained",
)
def test_voice_calibrator_loaded():
    from driveauth.matchers.voice import VoiceMatcher

    vm = VoiceMatcher.load(str(STORE / "enroll"), "driver1", store_dir=str(STORE))
    assert vm.ready
    assert vm.has_calibrator


def test_face_pad_features_shape():
    from driveauth.matchers.face_pad_features import (
        FACE_PAD_FEATURE_KEYS,
        extract_face_pad_features,
    )

    frame = np.random.randint(0, 255, (120, 100, 3), dtype=np.uint8)
    feats = extract_face_pad_features(frame, face_frac=0.4, frontal_ok=True)
    assert feats.shape == (len(FACE_PAD_FEATURE_KEYS),)
    assert feats.dtype == np.float32
