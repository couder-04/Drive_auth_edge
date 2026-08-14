"""Kinect / depth-liveness unit tests (no freenect hardware required)."""

from __future__ import annotations

import numpy as np
from hardware.ir_liveness import IRLivenessChecker, score_depth
from hardware.kinect_capture import (
    FreenectRGBBackend,
    KinectCapture,
    camera_backend_pref,
    freenect_available,
)


def _live_depth(size: int = 112, seed: int = 0) -> np.ndarray:
    """Disparity map with face-like relief and mostly valid samples."""
    rng = np.random.default_rng(seed)
    base = rng.normal(700, 15, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    # Nose bump toward camera (lower disparity distance in some modes;
    # we only need non-planar variance).
    base -= 40.0 * np.exp(-((yy - size / 2) ** 2 + (xx - size / 2) ** 2) / (2 * 18**2))
    return np.clip(base, 100, 1500)


def _flat_screen_depth(size: int = 112) -> np.ndarray:
    return np.full((size, size), 800.0, dtype=np.float32)


def _invalid_depth(size: int = 112) -> np.ndarray:
    return np.full((size, size), 2047.0, dtype=np.float32)


def test_score_depth_separates_live_and_spoof():
    live = score_depth(_live_depth())
    flat = score_depth(_flat_screen_depth())
    missing = score_depth(_invalid_depth())
    assert live > flat
    assert live >= 0.55
    assert flat < 0.45
    assert missing < 0.2


def test_score_depth_none():
    assert score_depth(None) == 0.0


def test_ensemble_uses_depth_when_provided():
    checker = IRLivenessChecker(threshold=0.55, ensemble=True)
    # Strong reflectance-like crop + blink burst + live depth.
    rng = np.random.default_rng(1)
    crop = np.clip(rng.normal(110, 25, (112, 112)), 0, 255).astype(np.float32)
    burst = [crop, np.roll(crop, 1, axis=0), crop.copy()]
    # Darken eye band mid-frame for blink proxy.
    mid = crop.copy()
    mid[28:56, :] = np.clip(mid[28:56, :] - 30, 0, 255)
    burst[1] = mid

    with_depth = checker.check(crop, frames=burst, depth=_live_depth())
    assert "depth" in with_depth.signal_scores
    assert with_depth.signal_scores["depth"] > 0.5

    no_depth = checker.check(crop, frames=burst, depth=None)
    assert "depth" not in no_depth.signal_scores


def test_ensemble_depth_pulls_down_flat_spoof():
    checker = IRLivenessChecker(threshold=0.55, ensemble=True)
    rng = np.random.default_rng(2)
    crop = np.clip(rng.normal(110, 25, (112, 112)), 0, 255).astype(np.float32)
    burst = [crop, np.roll(crop, 1, 0), np.roll(crop, -1, 0)]
    result = checker.check(crop, frames=burst, depth=_flat_screen_depth())
    assert result.signal_scores.get("depth", 1.0) < 0.5


def test_camera_backend_pref(monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_CAMERA_BACKEND", "kinect")
    assert camera_backend_pref() == "kinect"
    monkeypatch.setenv("DRIVEAUTH_CAMERA_BACKEND", "opencv")
    assert camera_backend_pref() == "opencv"


def test_freenect_rgb_backend_without_sdk():
    if freenect_available():
        return
    backend = FreenectRGBBackend(0)
    assert backend.open(0) is False


def test_kinect_capture_inject_backends():
    """KinectCapture works with numpy stand-ins (CI without freenect)."""

    class _FakeRGB:
        def __init__(self):
            self._open = False

        def open(self, index: int) -> bool:
            self._open = True
            return True

        def read(self):
            return np.zeros((480, 640, 3), dtype=np.uint8)

        def close(self) -> None:
            self._open = False

    class _FakeDepth:
        def open(self, index=None) -> bool:
            return True

        def read(self):
            return np.full((480, 640), 700, dtype=np.uint16)

        def close(self) -> None:
            return None

    cap = KinectCapture(rgb_backend=_FakeRGB(), depth_backend=_FakeDepth())
    assert cap.start() is True
    assert cap.depth_available is True
    bgr = cap.capture_bgr()
    assert bgr is not None and bgr.shape[0] == 112
    depth = cap.capture_depth_crop()
    assert depth is not None and depth.shape == (112, 112)
    gray = cap.capture_gray()
    assert gray is not None
    cap.stop()
    assert cap.started is False
