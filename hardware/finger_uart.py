"""UART fingerprint sensor adapters.

``FingerMatcher`` expects a Unix-socket daemon to return a raw 256×256
grayscale scan (``SCAN\\n`` → bytes). Sensor SDKs differ; isolate them behind
:class:`FingerSensorAdapter` so swapping vendors is a one-file change.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger("driveauth.hardware.finger_uart")

SCAN_WIDTH = 256
SCAN_HEIGHT = 256
SCAN_BYTES = SCAN_WIDTH * SCAN_HEIGHT


@runtime_checkable
class FingerSensorAdapter(Protocol):
    """Minimal capture contract for the finger daemon."""

    def open(self) -> bool:
        """Connect to the sensor. False → daemon reports unavailable."""
        ...

    def close(self) -> None:
        ...

    def capture_image(self) -> bytes | None:
        """Return ``SCAN_BYTES`` raw uint8 pixels, or None on failure."""
        ...


class ManualFingerSensor:
    """Dashboard / CI stand-in: serves a fixed (or slider-bridged) scan buffer.

    ``ManualScores(finger=0.x)`` still goes through ``MockFingerMatcher`` and
    never needs this sensor. Use this when the Unix-socket path must stay up
    without UART hardware (integration demos).
    """

    def __init__(self, scan: bytes | None = None):
        self._scan = scan
        self._open = False

    def set_scan(self, scan: bytes | None) -> None:
        if scan is not None and len(scan) < SCAN_BYTES:
            raise ValueError(f"scan must be ≥ {SCAN_BYTES} bytes")
        self._scan = scan

    def open(self) -> bool:
        self._open = True
        return True

    def close(self) -> None:
        self._open = False

    def capture_image(self) -> bytes | None:
        if not self._open:
            return None
        if self._scan is not None:
            return self._scan[:SCAN_BYTES]
        # Synthetic mid-gray contact pad — enough bytes for FingerMatcher shape checks.
        img = np.full((SCAN_HEIGHT, SCAN_WIDTH), 128, dtype=np.uint8)
        return img.tobytes()


class PyFingerprintAdapter:
    """Adapter for ``pyfingerprint`` (R303 / ZFM-20 family over UART).

    Import is deferred so hosts without the SDK still install cleanly.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        *,
        baud_rate: int = 57600,
        address: int = 0xFFFFFFFF,
        password: int = 0x00000000,
    ):
        self._port = port
        self._baud_rate = baud_rate
        self._address = address
        self._password = password
        self._sensor = None

    def open(self) -> bool:
        try:
            from pyfingerprint import PyFingerprint  # type: ignore
        except ImportError:
            logger.warning("PyFingerprintAdapter: pyfingerprint not installed")
            return False
        try:
            sensor = PyFingerprint(
                self._port,
                self._baud_rate,
                self._address,
                self._password,
            )
            if not sensor.verifyPassword():
                logger.error("PyFingerprintAdapter: password verify failed")
                return False
            self._sensor = sensor
            return True
        except Exception as exc:
            logger.error("PyFingerprintAdapter: open failed (%s)", type(exc).__name__)
            self._sensor = None
            return False

    def close(self) -> None:
        self._sensor = None

    def capture_image(self) -> bytes | None:
        sensor = self._sensor
        if sensor is None:
            return None
        try:
            while not sensor.readImage():
                pass
            # downloadCharacteristics yields a list of 8-bit values for the image.
            raw = sensor.downloadImage()
            if raw is None:
                return None
            if isinstance(raw, (bytes, bytearray)):
                buf = bytes(raw)
            else:
                buf = bytes(int(x) & 0xFF for x in raw)
            if len(buf) < SCAN_BYTES:
                # Pad / center-crop odd sensor resolutions into the matcher contract.
                padded = bytearray(SCAN_BYTES)
                padded[: min(len(buf), SCAN_BYTES)] = buf[:SCAN_BYTES]
                return bytes(padded)
            return buf[:SCAN_BYTES]
        except Exception as exc:
            logger.warning("PyFingerprintAdapter: capture failed (%s)", type(exc).__name__)
            return None
