"""Deterministic matchers for demos and unit tests."""

from __future__ import annotations

import numpy as np

from driveauth.types import ModalityResult


def _good_face_gray(size: int = 112) -> np.ndarray:
    """Sharp, mid-brightness synthetic face crop that passes QualityGate."""
    yy, xx = np.mgrid[0:size, 0:size]
    base = np.full((size, size), 130.0, dtype=np.float32)
    # High-frequency checker to raise Laplacian variance above blur threshold.
    base += ((xx // 2 + yy // 2) % 2) * 40.0
    return base.astype(np.float32)


def _bad_face_gray(size: int = 112) -> np.ndarray:
    """Near-uniform dark frame — fails blur + brightness gates."""
    return np.full((size, size), 10.0, dtype=np.float32)


class MockVoiceMatcher:
    def __init__(self, score: float = 0.92, confident: bool = True):
        self._score = score
        self._confident = confident

    def score(self, audio_f32: np.ndarray, sample_rate: int = 16_000) -> ModalityResult:
        if audio_f32 is None or audio_f32.size < sample_rate // 2:
            return ModalityResult(None, False, available=False)
        return ModalityResult(
            self._score, self._confident, embedding=np.zeros(192, dtype=np.float32)
        )


class MockFaceMatcher:
    def __init__(
        self,
        score: float = 0.88,
        confident: bool = True,
        *,
        available: bool = True,
        bad_quality: bool = False,
        face_frac: float = 0.35,
        frontal_ok: bool = True,
    ):
        self._score = score
        self._confident = confident
        self._available = available
        self._bad_quality = bad_quality
        self.face_frac = face_frac
        self.frontal_ok = frontal_ok

    def capture_frame(self) -> np.ndarray | None:
        if not self._available:
            return None
        return _bad_face_gray() if self._bad_quality else _good_face_gray()

    def score_frame(self, frame_gray: np.ndarray) -> ModalityResult:
        if not self._available or frame_gray is None:
            return ModalityResult(None, False, available=False)
        return ModalityResult(
            self._score, self._confident, embedding=np.zeros(128, dtype=np.float32)
        )

    def capture_and_score(self) -> ModalityResult:
        frame = self.capture_frame()
        if frame is None:
            return ModalityResult(None, False, available=False)
        return self.score_frame(frame)


class MockFingerMatcher:
    def __init__(
        self,
        score: float | None = 0.85,
        confident: bool = True,
        *,
        available: bool = True,
        contact: float = 0.8,
        pressure: float = 0.7,
        clarity: float = 0.9,
        bad_quality: bool = False,
    ):
        self._score = score
        self._confident = confident
        self._available = available
        self.contact = 0.1 if bad_quality else contact
        self.pressure = 0.1 if bad_quality else pressure
        self.clarity = clarity

    def capture_metrics(self) -> tuple[float | None, float | None, float | None]:
        if not self._available:
            return None, None, None
        return self.contact, self.clarity, self.pressure

    def score_scan(self) -> ModalityResult:
        if not self._available or self._score is None:
            return ModalityResult(None, False, available=False)
        return ModalityResult(
            self._score, self._confident, embedding=np.zeros(64, dtype=np.float32)
        )

    def capture_and_score(self) -> ModalityResult:
        return self.score_scan()


class MockBehavioralMonitor:
    def __init__(self, score: float = 0.95, *, available: bool = True):
        self._score = score
        self._available = available

    def update(self, sensor: dict[str, float]) -> None:
        pass

    @property
    def available(self) -> bool:
        return self._available

    def get_score(self) -> ModalityResult:
        if not self._available:
            return ModalityResult(score=None, confident=False, available=False)
        return ModalityResult(self._score, confident=True, available=True)
