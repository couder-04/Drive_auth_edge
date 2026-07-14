"""Stage 1 — OOD negatives + trust fusion stays static."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from driveauth.fusion import TrustFusion
from driveauth.ood_detector import OODDetector
from driveauth.types import ModalityResult

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "driveauth_store_phase2a"
DATA = ROOT / "data" / "driver1"


def test_trust_fusion_stays_static_weighted_average():
    """Static path (no ONNX) keeps weighted-average Trust (Stage 1 contract)."""
    fusion = TrustFusion(orchestrator=None, logreg=None)
    assert fusion.mode == "static"
    voice = ModalityResult(score=0.9, confident=True, quality=1.0)
    face = ModalityResult(score=0.6, confident=True, quality=1.0)
    finger = ModalityResult(score=None, confident=False, available=False)
    trust, eff = fusion.fuse(voice, face, finger)
    assert set(eff) == {"voice", "face"}
    # Renormalized 0.3/0.4 → 0.4286 / 0.5714
    assert abs(eff["voice"] - 0.3 / 0.7) < 1e-6
    assert abs(eff["face"] - 0.4 / 0.7) < 1e-6
    expected = (0.3 / 0.7) * 0.9 + (0.4 / 0.7) * 0.6
    assert abs(trust - expected) < 1e-6
    assert fusion.last_mode == "static"


def test_ood_detector_flags_far_embedding():
    import tempfile

    tmp = tempfile.mkdtemp(prefix="driveauth_ood_")
    OODDetector.seed_baselines(tmp, "driver1", voice_dim=8, face_dim=8, finger_dim=8)
    ood_dir = Path(tmp) / "ood_stats"
    mean = np.zeros(8, dtype=np.float32)
    std = np.ones(8, dtype=np.float32) * 0.1
    np.savez(ood_dir / "voice_driver1.npz", mean=mean, std=std)
    np.savez(ood_dir / "face_driver1.npz", mean=mean, std=std)

    det = OODDetector.load(tmp, "driver1")
    in_dist = np.zeros(8, dtype=np.float32)
    far = np.ones(8, dtype=np.float32) * 5.0
    assert det.voice.is_ood(in_dist)[0] is False
    assert det.voice.is_ood(far)[0] is True
    assert det.face.is_ood(far)[0] is True


@pytest.mark.skipif(
    not (DATA / "ood" / "voice").exists()
    or len(list((DATA / "ood" / "voice").glob("*.wav"))) < 3,
    reason="OOD voice WAVs missing",
)
def test_ood_voice_files_are_nontrivial():
    wavs = list((DATA / "ood" / "voice").glob("*.wav"))
    assert sum(1 for p in wavs if p.stat().st_size > 1000) >= 3


@pytest.mark.skipif(
    not (STORE / "faces" / "driver1.enc").exists()
    or not (DATA / "ood" / "face").exists(),
    reason="Phase 2a store or OOD face set missing",
)
def test_ood_face_negatives_reject_against_enrolled_template():
    """Real other-identity faces should not match enrolled driver1 strongly."""
    import cv2  # type: ignore

    from driveauth.matchers.face import FaceMatcher

    fm = FaceMatcher.load(str(STORE), "driver1")
    if not fm.ready:
        pytest.skip("FaceMatcher not ready")
    images = sorted((DATA / "ood" / "face").glob("*.jpg"))[:10]
    assert images, "no OOD face images"
    scores = []
    for p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        emb = fm.embed_bgr(bgr)
        if emb is None or fm._emb is None:
            continue
        scores.append(float(np.dot(fm._emb, emb)))
    assert len(scores) >= 3
    # Own-face enroll still has attack overlap; OOD other-id should sit lower.
    assert float(np.mean(scores)) < 0.75
    assert float(np.max(scores)) < 0.90
