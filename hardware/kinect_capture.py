"""Xbox Kinect (libfreenect) capture backends for face / depth / mic.

Targets the **Xbox 360 Kinect** (v1 / model 1414/1473) via optional
``freenect`` Python bindings (system ``libfreenect``). Xbox One Kinect (v2)
needs ``libfreenect2`` and is not covered here.

When freenect is absent, RGB falls back to OpenCV ``VideoCapture`` so a
V4L2-exposed Kinect (or any USB cam) still works; depth stays unavailable
until freenect is installed.

Env:
  ``DRIVEAUTH_CAMERA_BACKEND`` = ``auto`` | ``kinect`` | ``opencv``
  ``DRIVEAUTH_KINECT_INDEX``   = freenect device index (default 0)
  ``DRIVEAUTH_MIC_DEVICE``     = PortAudio device index or substring name
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import numpy as np

from hardware.ir_capture import (
    FACE_CROP_SIZE,
    VOICE_SAMPLE_RATE,
    AudioBackend,
    FrameBackend,
    IRCameraCapture,
    MicArrayCapture,
    NumpyAudioBackend,
    OpenCVFrameBackend,
    _center_crop_square,
)

logger = logging.getLogger("driveauth.hardware.kinect")

# Kinect v1 depth: 11-bit disparity; 0 / 2047 often mean invalid.
_DEPTH_INVALID = 2047


def camera_backend_pref() -> str:
    raw = (os.getenv("DRIVEAUTH_CAMERA_BACKEND", "auto") or "auto").strip().lower()
    if raw in ("auto", "kinect", "opencv", "freenect"):
        return "opencv" if raw == "opencv" else ("kinect" if raw in ("kinect", "freenect") else "auto")
    return "auto"


def kinect_index() -> int:
    try:
        return int(os.getenv("DRIVEAUTH_KINECT_INDEX", "0") or "0")
    except ValueError:
        return 0


def freenect_available() -> bool:
    try:
        import freenect  # type: ignore  # noqa: F401

        return True
    except ImportError:
        return False


class FreenectRGBBackend:
    """``FrameBackend`` over ``freenect.sync_get_video`` → BGR uint8."""

    def __init__(self, index: int | None = None):
        self._index = kinect_index() if index is None else int(index)
        self._open = False

    def open(self, index: int) -> bool:
        if not freenect_available():
            logger.warning("FreenectRGBBackend: freenect not installed")
            return False
        self._index = int(index) if index is not None else self._index
        # Probe one frame so we fail early if USB claim fails.
        frame = self.read()
        self._open = frame is not None
        if not self._open:
            logger.warning("FreenectRGBBackend: no video frame from Kinect %s", self._index)
        return self._open

    def read(self) -> np.ndarray | None:
        try:
            import freenect  # type: ignore

            pair = freenect.sync_get_video(self._index)
            if pair is None:
                return None
            rgb, _ts = pair
            if rgb is None:
                return None
            img = np.asarray(rgb)
            if img.ndim != 3 or img.shape[2] < 3:
                return None
            # freenect returns RGB; OpenCV / FaceMatcher expect BGR.
            return img[:, :, ::-1].copy()
        except Exception as exc:
            logger.warning("FreenectRGBBackend: read failed (%s)", type(exc).__name__)
            return None

    def close(self) -> None:
        self._open = False
        try:
            import freenect  # type: ignore

            freenect.sync_stop()
        except Exception:
            pass


class FreenectDepthBackend:
    """Raw Kinect depth frames (uint16, 480×640)."""

    def __init__(self, index: int | None = None):
        self._index = kinect_index() if index is None else int(index)
        self._open = False

    def open(self, index: int | None = None) -> bool:
        if not freenect_available():
            return False
        if index is not None:
            self._index = int(index)
        depth = self.read()
        self._open = depth is not None
        return self._open

    def read(self) -> np.ndarray | None:
        try:
            import freenect  # type: ignore

            pair = freenect.sync_get_depth(self._index)
            if pair is None:
                return None
            depth, _ts = pair
            if depth is None:
                return None
            return np.asarray(depth, dtype=np.uint16)
        except Exception as exc:
            logger.warning("FreenectDepthBackend: read failed (%s)", type(exc).__name__)
            return None

    def close(self) -> None:
        self._open = False


class SoundDeviceAudioBackend:
    """PortAudio capture via optional ``sounddevice`` package."""

    def __init__(self, device: int | str | None = None):
        env = os.getenv("DRIVEAUTH_MIC_DEVICE", "").strip()
        if device is None and env:
            device = int(env) if env.isdigit() else env
        self._device = device
        self._stream = None
        self._sr = VOICE_SAMPLE_RATE
        self._channels = 1

    def open(self, sample_rate: int, channels: int) -> bool:
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            logger.warning(
                "SoundDeviceAudioBackend: sounddevice not installed "
                "(pip install sounddevice)"
            )
            return False
        self._sr = int(sample_rate)
        self._channels = max(1, int(channels))
        device = self._resolve_device(sd)
        try:
            self._stream = sd.InputStream(
                samplerate=self._sr,
                channels=self._channels,
                dtype="float32",
                device=device,
            )
            self._stream.start()
            logger.info(
                "SoundDeviceAudioBackend: opened device=%s sr=%d",
                device,
                self._sr,
            )
            return True
        except Exception as exc:
            logger.warning(
                "SoundDeviceAudioBackend: open failed (%s)", type(exc).__name__
            )
            self._stream = None
            return False

    def _resolve_device(self, sd: Any) -> int | str | None:
        if self._device is None or self._device == "":
            return None
        if isinstance(self._device, int):
            return self._device
        name = str(self._device).lower()
        try:
            for i, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) <= 0:
                    continue
                if name in str(info.get("name", "")).lower():
                    return i
        except Exception:
            pass
        return self._device

    def read(self, frames: int) -> np.ndarray | None:
        if self._stream is None:
            return None
        try:
            data, _overflowed = self._stream.read(max(1, int(frames)))
            audio = np.asarray(data, dtype=np.float32)
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            return audio.reshape(-1)
        except Exception as exc:
            logger.warning("SoundDeviceAudioBackend: read failed (%s)", type(exc).__name__)
            return None

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


class KinectCapture:
    """RGB + depth face crops for IR liveness / FaceMatcher inject paths.

    Exposes the same gray/burst helpers as :class:`IRCameraCapture` plus
    ``capture_depth_crop`` for the depth liveness signal.
    """

    def __init__(
        self,
        *,
        index: int | None = None,
        crop_size: int = FACE_CROP_SIZE,
        rgb_backend: FrameBackend | None = None,
        depth_backend: FreenectDepthBackend | None = None,
    ):
        self._index = kinect_index() if index is None else int(index)
        self._crop_size = int(crop_size)
        self._rgb: FrameBackend = rgb_backend or FreenectRGBBackend(self._index)
        self._depth = depth_backend if depth_backend is not None else FreenectDepthBackend(
            self._index
        )
        self._started = False
        self._depth_ok = False
        self._lock = threading.Lock()
        self._last_face_box: tuple[int, int, int, int] | None = None

    def start(self) -> bool:
        with self._lock:
            if self._started:
                return True
            ok = bool(self._rgb.open(self._index))
            self._depth_ok = bool(self._depth.open(self._index))
            self._started = ok
            if not ok:
                logger.warning("KinectCapture: RGB open failed (index=%s)", self._index)
            elif not self._depth_ok:
                logger.warning("KinectCapture: depth unavailable — RGB-only mode")
            else:
                logger.info("KinectCapture: RGB+depth ready (index=%s)", self._index)
            return ok

    def stop(self) -> None:
        with self._lock:
            try:
                self._rgb.close()
            except Exception:
                pass
            try:
                self._depth.close()
            except Exception:
                pass
            self._started = False
            self._depth_ok = False

    @property
    def started(self) -> bool:
        return self._started

    @property
    def depth_available(self) -> bool:
        return self._depth_ok

    def capture(self) -> np.ndarray | None:
        """BGR face-region crop."""
        with self._lock:
            if not self._started:
                return None
            try:
                frame = self._rgb.read()
            except Exception as exc:
                logger.warning("KinectCapture: RGB read failed (%s)", type(exc).__name__)
                return None
            if frame is None:
                return None
            try:
                return _center_crop_square(frame, self._crop_size)
            except Exception as exc:
                logger.warning("KinectCapture: crop failed (%s)", type(exc).__name__)
                return None

    def capture_bgr(self) -> np.ndarray | None:
        return self.capture()

    def capture_gray(self) -> np.ndarray | None:
        crop = self.capture()
        if crop is None:
            return None
        if crop.ndim == 2:
            return crop.astype(np.float32)
        return crop.astype(np.float32).mean(axis=2)

    def capture_gray_burst(self, n: int = 3) -> list[np.ndarray]:
        n = max(1, int(n))
        out: list[np.ndarray] = []
        for _ in range(n):
            frame = self.capture_gray()
            if frame is not None:
                out.append(frame)
        return out

    def capture_depth(self) -> np.ndarray | None:
        """Full-resolution uint16 depth frame, or None."""
        with self._lock:
            if not self._started or not self._depth_ok:
                return None
            return self._depth.read()

    def capture_depth_crop(self) -> np.ndarray | None:
        """Center-square depth crop resized to ``crop_size`` (float32 mm/raw)."""
        depth = self.capture_depth()
        if depth is None:
            return None
        try:
            img = np.asarray(depth)
            h, w = img.shape[:2]
            side = min(h, w)
            y0, x0 = (h - side) // 2, (w - side) // 2
            crop = img[y0 : y0 + side, x0 : x0 + side].astype(np.float32)
            try:
                import cv2  # type: ignore

                return cv2.resize(crop, (self._crop_size, self._crop_size))
            except ImportError:
                ys = (np.linspace(0, crop.shape[0] - 1, self._crop_size)).astype(np.int32)
                xs = (np.linspace(0, crop.shape[1] - 1, self._crop_size)).astype(np.int32)
                return crop[ys][:, xs]
        except Exception as exc:
            logger.warning("KinectCapture: depth crop failed (%s)", type(exc).__name__)
            return None


def open_ir_capture(
    camera_index: int,
    *,
    prefer: str | None = None,
) -> IRCameraCapture | KinectCapture:
    """Factory used by ``DriveAuth._attach_ir_liveness``.

    ``prefer`` overrides ``DRIVEAUTH_CAMERA_BACKEND``. Returns a started
    capture when possible; caller may still swap to a numpy inject backend.
    """
    pref = (prefer or camera_backend_pref()).strip().lower()
    if pref in ("kinect", "auto") and freenect_available():
        cap = KinectCapture(index=kinect_index())
        if cap.start():
            return cap
        cap.stop()
        if pref == "kinect":
            logger.warning("open_ir_capture: Kinect requested but start failed")
    # OpenCV / V4L2 path (USB cam or Kinect RGB via gspca).
    cap_cv = IRCameraCapture(camera_index, backend=OpenCVFrameBackend())
    if cap_cv.start():
        return cap_cv
    return cap_cv


def open_mic_capture(*, default_seconds: float = 1.5) -> MicArrayCapture:
    """Prefer PortAudio (Kinect mic / USB array); fall back to numpy inject."""
    backend: AudioBackend = SoundDeviceAudioBackend()
    mic = MicArrayCapture(backend=backend, default_seconds=default_seconds)
    if mic.start():
        return mic
    mic.stop()
    fallback = MicArrayCapture(
        backend=NumpyAudioBackend(), default_seconds=default_seconds
    )
    fallback.start()
    return fallback
