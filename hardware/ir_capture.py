"""Camera / mic capture services for DriveAuth matchers.

Each service is a small standalone class with ``start()``, ``stop()``, and
``capture()`` — no global state, no coupling to ``decision_engine``.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger("driveauth.hardware.capture")

FACE_CROP_SIZE = 112
VOICE_SAMPLE_RATE = 16_000


@runtime_checkable
class FrameBackend(Protocol):
    def open(self, index: int) -> bool: ...
    def read(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


@runtime_checkable
class AudioBackend(Protocol):
    def open(self, sample_rate: int, channels: int) -> bool: ...
    def read(self, frames: int) -> np.ndarray | None: ...
    def close(self) -> None: ...


class NumpyFrameBackend:
    """Test / inject stand-in: serves a fixed frame on every read."""

    def __init__(self, frame: np.ndarray | None = None):
        self._frame = frame
        self._open = False

    def set_frame(self, frame: np.ndarray | None) -> None:
        self._frame = None if frame is None else np.asarray(frame)

    def open(self, index: int) -> bool:
        self._open = True
        return True

    def read(self) -> np.ndarray | None:
        if not self._open or self._frame is None:
            return None
        return np.asarray(self._frame).copy()

    def close(self) -> None:
        self._open = False


class OpenCVFrameBackend:
    """OpenCV VideoCapture wrapper (optional ``opencv-python`` extra)."""

    def __init__(self):
        self._cap = None

    def open(self, index: int) -> bool:
        try:
            import cv2  # type: ignore
        except ImportError:
            logger.warning("OpenCVFrameBackend: opencv not installed")
            return False
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        return True

    def read(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None


class NumpyAudioBackend:
    """Test stand-in: returns a fixed mono float32 buffer."""

    def __init__(self, audio: np.ndarray | None = None):
        self._audio = audio
        self._open = False

    def set_audio(self, audio: np.ndarray | None) -> None:
        self._audio = None if audio is None else np.asarray(audio, dtype=np.float32)

    def open(self, sample_rate: int, channels: int) -> bool:
        self._open = True
        return True

    def read(self, frames: int) -> np.ndarray | None:
        if not self._open or self._audio is None:
            return None
        buf = np.asarray(self._audio, dtype=np.float32).reshape(-1)
        if buf.size < frames:
            out = np.zeros(frames, dtype=np.float32)
            out[: buf.size] = buf
            return out
        return buf[:frames].copy()

    def close(self) -> None:
        self._open = False


def _center_crop_square(frame: np.ndarray, size: int = FACE_CROP_SIZE) -> np.ndarray:
    img = np.asarray(frame)
    if img.ndim == 3:
        h, w = img.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        crop = img[y0 : y0 + side, x0 : x0 + side]
        try:
            import cv2  # type: ignore

            return cv2.resize(crop, (size, size))
        except ImportError:
            # Nearest-neighbor fallback without OpenCV.
            ys = (np.linspace(0, crop.shape[0] - 1, size)).astype(np.int32)
            xs = (np.linspace(0, crop.shape[1] - 1, size)).astype(np.int32)
            return crop[ys][:, xs]
    # Grayscale
    h, w = img.shape[:2]
    side = min(h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    crop = img[y0 : y0 + side, x0 : x0 + side]
    try:
        import cv2  # type: ignore

        return cv2.resize(crop, (size, size))
    except ImportError:
        ys = (np.linspace(0, crop.shape[0] - 1, size)).astype(np.int32)
        xs = (np.linspace(0, crop.shape[1] - 1, size)).astype(np.int32)
        return crop[ys][:, xs]


class _CameraCaptureBase:
    def __init__(
        self,
        camera_index: int,
        *,
        backend: FrameBackend | None = None,
        crop_size: int = FACE_CROP_SIZE,
    ):
        self._index = int(camera_index)
        self._backend: FrameBackend = backend or OpenCVFrameBackend()
        self._crop_size = crop_size
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._started:
                return True
            ok = bool(self._backend.open(self._index))
            self._started = ok
            if not ok:
                logger.warning("%s: camera %s open failed", type(self).__name__, self._index)
            return ok

    def stop(self) -> None:
        with self._lock:
            try:
                self._backend.close()
            except Exception:
                pass
            self._started = False

    def capture(self) -> np.ndarray | None:
        """Return a face-region crop as numpy array, or None (fail-closed)."""
        with self._lock:
            if not self._started:
                return None
            try:
                frame = self._backend.read()
            except Exception as exc:
                logger.warning("%s: read failed (%s)", type(self).__name__, type(exc).__name__)
                return None
            if frame is None:
                return None
            try:
                return _center_crop_square(frame, self._crop_size)
            except Exception as exc:
                logger.warning("%s: crop failed (%s)", type(self).__name__, type(exc).__name__)
                return None

    @property
    def started(self) -> bool:
        return self._started


class IRCameraCapture(_CameraCaptureBase):
    """IR camera → face crop (numpy) for ``driveauth.matchers.face``."""

    def capture_gray(self) -> np.ndarray | None:
        crop = self.capture()
        if crop is None:
            return None
        if crop.ndim == 2:
            return crop.astype(np.float32)
        # BGR/RGB → luminance
        return crop.astype(np.float32).mean(axis=2)


class RGBCameraCapture(_CameraCaptureBase):
    """USB RGB camera → face crop for cross-check against the IR crop."""

    def capture_bgr(self) -> np.ndarray | None:
        return self.capture()


class MicArrayCapture:
    """Mic array → 16 kHz mono float32 buffer for ``driveauth.matchers.voice``."""

    def __init__(
        self,
        *,
        sample_rate: int = VOICE_SAMPLE_RATE,
        backend: AudioBackend | None = None,
        default_seconds: float = 1.5,
    ):
        self._sr = int(sample_rate)
        self._backend: AudioBackend = backend or NumpyAudioBackend()
        self._default_seconds = float(default_seconds)
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._started:
                return True
            ok = bool(self._backend.open(self._sr, 1))
            self._started = ok
            return ok

    def stop(self) -> None:
        with self._lock:
            try:
                self._backend.close()
            except Exception:
                pass
            self._started = False

    def capture(self, seconds: float | None = None) -> np.ndarray | None:
        """Return mono float32 at ``sample_rate``, or None if unavailable."""
        with self._lock:
            if not self._started:
                return None
            dur = self._default_seconds if seconds is None else float(seconds)
            frames = max(1, int(round(dur * self._sr)))
            try:
                buf = self._backend.read(frames)
            except Exception as exc:
                logger.warning("MicArrayCapture: read failed (%s)", type(exc).__name__)
                return None
            if buf is None:
                return None
            audio = np.asarray(buf, dtype=np.float32).reshape(-1)
            if audio.size == 0:
                return None
            return audio

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def started(self) -> bool:
        return self._started
