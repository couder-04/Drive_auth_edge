"""UART fingerprint sensor adapters.

``FingerMatcher`` expects a Unix-socket daemon to return a raw 256×256
grayscale scan (``SCAN\\n`` → bytes). Sensor SDKs differ; isolate them behind
:class:`FingerSensorAdapter` so swapping vendors is a one-file change.

Default concrete adapter: :class:`PyFingerprintAdapter` for the common
R307 / AS608 / R303 / ZFM-20 UART family that ``pyfingerprint`` targets.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

logger = logging.getLogger("driveauth.hardware.finger_uart")

SCAN_WIDTH = 256
SCAN_HEIGHT = 256
SCAN_BYTES = SCAN_WIDTH * SCAN_HEIGHT

# Common USB-serial device nodes for CH340/CP2102/FTDI bridges on R307/AS608.
DEFAULT_PROBE_PORTS: tuple[str, ...] = (
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyAMA0",
    "/dev/serial0",
    "/dev/ttyACM0",
)

# Busy-wait budget for finger contact before failing the capture.
_READ_IMAGE_TIMEOUT_S = float(os.getenv("DRIVEAUTH_FINGER_CAPTURE_TIMEOUT_S", "8.0") or "8.0")


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


def _normalize_scan_bytes(raw) -> bytes | None:
    """Coerce pyfingerprint download payloads into exactly ``SCAN_BYTES``."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        buf = bytes(raw)
    else:
        try:
            buf = bytes(int(x) & 0xFF for x in raw)
        except TypeError:
            return None
    if not buf:
        return None
    if len(buf) < SCAN_BYTES:
        # Pad / center-crop odd sensor resolutions into the matcher contract.
        padded = bytearray(SCAN_BYTES)
        padded[: min(len(buf), SCAN_BYTES)] = buf[:SCAN_BYTES]
        return bytes(padded)
    return buf[:SCAN_BYTES]


class PyFingerprintAdapter:
    """Concrete UART adapter for R307 / AS608 / R303 / ZFM-20 modules.

    Uses the optional ``pyfingerprint`` package (same protocol family across
    these sensors). Import is deferred so hosts without the SDK still install
    cleanly. ``open()`` returns False when the library or device is absent —
    never raises to the daemon.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        *,
        baud_rate: int = 57600,
        address: int = 0xFFFFFFFF,
        password: int = 0x00000000,
        capture_timeout_s: float | None = None,
    ):
        self._port = port
        self._baud_rate = baud_rate
        self._address = address
        self._password = password
        self._capture_timeout_s = (
            _READ_IMAGE_TIMEOUT_S if capture_timeout_s is None else float(capture_timeout_s)
        )
        self._sensor = None

    @property
    def port(self) -> str:
        return self._port

    @property
    def connected(self) -> bool:
        return self._sensor is not None

    def open(self) -> bool:
        try:
            from pyfingerprint import PyFingerprint  # type: ignore
        except ImportError:
            logger.warning(
                "PyFingerprintAdapter: pyfingerprint not installed "
                "(pip install 'driveauth-edge[finger]')"
            )
            return False
        if not Path(self._port).exists():
            logger.warning("PyFingerprintAdapter: port %s not found", self._port)
            return False
        try:
            sensor = PyFingerprint(
                self._port,
                self._baud_rate,
                self._address,
                self._password,
            )
            if not sensor.verifyPassword():
                logger.error(
                    "PyFingerprintAdapter: password verify failed on %s", self._port
                )
                return False
            self._sensor = sensor
            logger.info(
                "PyFingerprintAdapter: opened R307/AS608-class sensor on %s",
                self._port,
            )
            return True
        except Exception as exc:
            logger.error(
                "PyFingerprintAdapter: open failed on %s (%s)",
                self._port,
                type(exc).__name__,
            )
            self._sensor = None
            return False

    def close(self) -> None:
        self._sensor = None

    def capture_image(self) -> bytes | None:
        sensor = self._sensor
        if sensor is None:
            return None
        try:
            deadline = time.monotonic() + max(0.5, self._capture_timeout_s)
            while not sensor.readImage():
                if time.monotonic() >= deadline:
                    logger.warning(
                        "PyFingerprintAdapter: readImage timed out after %.1fs",
                        self._capture_timeout_s,
                    )
                    return None
                time.sleep(0.05)
            raw = sensor.downloadImage()
            return _normalize_scan_bytes(raw)
        except Exception as exc:
            logger.warning(
                "PyFingerprintAdapter: capture failed (%s)", type(exc).__name__
            )
            return None


# Explicit aliases for the module families we target.
R307Adapter = PyFingerprintAdapter
AS608Adapter = PyFingerprintAdapter


def candidate_ports(preferred: str | None = None) -> list[str]:
    """Ordered unique UART nodes to probe for an R307/AS608-class sensor."""
    env = os.getenv("DRIVEAUTH_FINGER_UART", "").strip()
    ordered: list[str] = []
    for p in (preferred, env or None, *DEFAULT_PROBE_PORTS):
        if p and p not in ordered:
            ordered.append(p)
    return ordered


def probe_pyfingerprint(
    port: str | None = None,
    *,
    baud_rate: int = 57600,
) -> PyFingerprintAdapter | None:
    """Try to open a real UART sensor. Returns a connected adapter or None."""
    for candidate in candidate_ports(port):
        adapter = PyFingerprintAdapter(candidate, baud_rate=baud_rate)
        if adapter.open():
            return adapter
        adapter.close()
    return None


def open_default_sensor(
    *,
    port: str | None = None,
    manual: bool = False,
    allow_manual_fallback: bool = True,
) -> tuple[FingerSensorAdapter, str]:
    """Select the live sensor for the finger daemon.

    Preference order:
    1. ``ManualFingerSensor`` when ``manual=True`` / ``DRIVEAUTH_FINGER_MANUAL=1``
    2. Probed :class:`PyFingerprintAdapter` when a UART module answers
    3. ``ManualFingerSensor`` fallback (so the Unix-socket path stays up for
       demos) when ``allow_manual_fallback`` — otherwise raises ``RuntimeError``

    Returns ``(sensor, kind)`` where ``kind`` is ``"manual"``, ``"pyfingerprint"``,
    or ``"manual_fallback"``.
    """
    force_manual = manual or os.getenv("DRIVEAUTH_FINGER_MANUAL", "0") == "1"
    if force_manual:
        logger.info("Finger sensor: ManualFingerSensor (DRIVEAUTH_FINGER_MANUAL)")
        return ManualFingerSensor(), "manual"

    real = probe_pyfingerprint(port)
    if real is not None:
        return real, "pyfingerprint"

    if allow_manual_fallback:
        logger.warning(
            "Finger sensor: no R307/AS608 UART detected — falling back to "
            "ManualFingerSensor (set DRIVEAUTH_FINGER_MANUAL=1 to silence)"
        )
        return ManualFingerSensor(), "manual_fallback"

    raise RuntimeError(
        "No fingerprint UART sensor detected and manual fallback disabled"
    )
