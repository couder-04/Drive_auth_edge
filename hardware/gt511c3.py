"""GT-511C3 / ADH-Tech UART fingerprint adapter.

Protocol family differs from ZFM (R307/AS608 / ``pyfingerprint``):
  - Default baud **9600** 8N1 (not 57600)
  - Packet header ``0x55 0xAA`` (cmd/ack) / ``0x5A 0xA5`` (data)
  - GetImage payload is **258×202** (52_116 bytes), not 256×256

:class:`GT511C3Adapter` implements :class:`FingerSensorAdapter` and returns
exactly ``SCAN_BYTES`` (256×256) via letterbox + resize so ``FingerMatcher``
and the Unix-socket daemon stay vendor-agnostic.
"""

from __future__ import annotations

import logging
import os
import struct
import time
from pathlib import Path

import numpy as np

from hardware.finger_uart import SCAN_BYTES, SCAN_HEIGHT, SCAN_WIDTH

logger = logging.getLogger("driveauth.hardware.gt511c3")

# Command / response
_CMD_START = b"\x55\xaa"
_DATA_START = b"\x5a\xa5"
_DEVICE_ID = 0x0001

CMD_OPEN = 0x01
CMD_CLOSE = 0x02
CMD_CHANGE_BAUD = 0x04
CMD_CMOS_LED = 0x12
CMD_IS_PRESS_FINGER = 0x26
CMD_CAPTURE_FINGER = 0x60
CMD_GET_IMAGE = 0x62
CMD_GET_RAW_IMAGE = 0x63
CMD_ACK = 0x30
CMD_NACK = 0x31

# Datasheet GetImage size (258×202).
GT511_IMAGE_W = 258
GT511_IMAGE_H = 202
GT511_IMAGE_BYTES = GT511_IMAGE_W * GT511_IMAGE_H  # 52116

DEFAULT_BAUD = 9600
FAST_BAUD = 115200

_CAPTURE_TIMEOUT_S = float(os.getenv("DRIVEAUTH_FINGER_CAPTURE_TIMEOUT_S", "8.0") or "8.0")
_IO_TIMEOUT_S = float(os.getenv("DRIVEAUTH_GT511_IO_TIMEOUT_S", "3.0") or "3.0")


def _u16_le(value: int) -> bytes:
    return struct.pack("<H", int(value) & 0xFFFF)


def _u32_le(value: int) -> bytes:
    return struct.pack("<I", int(value) & 0xFFFFFFFF)


def build_command(command: int, parameter: int = 0) -> bytes:
    """12-byte little-endian command packet with additive checksum."""
    body = (
        _CMD_START
        + _u16_le(_DEVICE_ID)
        + _u32_le(parameter)
        + _u16_le(command)
    )
    checksum = sum(body) & 0xFFFF
    return body + _u16_le(checksum)


def parse_response(buf: bytes) -> tuple[bool, int, int] | None:
    """Return ``(ack, parameter, response_code)`` or None if malformed."""
    if len(buf) < 12:
        return None
    if buf[0:2] != _CMD_START:
        return None
    if struct.unpack_from("<H", buf, 2)[0] != _DEVICE_ID:
        return None
    parameter = struct.unpack_from("<I", buf, 4)[0]
    response = struct.unpack_from("<H", buf, 8)[0]
    checksum = struct.unpack_from("<H", buf, 10)[0]
    if (sum(buf[:10]) & 0xFFFF) != checksum:
        return None
    if response == CMD_ACK:
        return True, parameter, response
    if response == CMD_NACK:
        return False, parameter, response
    return None


def resize_gt511_to_scan(raw: bytes | np.ndarray) -> bytes | None:
    """Letterbox 258×202 (or HxW uint8) into exactly ``SCAN_BYTES``."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) < GT511_IMAGE_BYTES:
            return None
        img = np.frombuffer(raw[:GT511_IMAGE_BYTES], dtype=np.uint8).reshape(
            GT511_IMAGE_H, GT511_IMAGE_W
        )
    else:
        img = np.asarray(raw, dtype=np.uint8)
        if img.ndim != 2 or img.size == 0:
            return None

    # Prefer OpenCV when present; otherwise nearest-neighbour letterbox.
    try:
        import cv2  # type: ignore

        scale = min(SCAN_WIDTH / img.shape[1], SCAN_HEIGHT / img.shape[0])
        nw = max(1, round(img.shape[1] * scale))
        nh = max(1, round(img.shape[0] * scale))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((SCAN_HEIGHT, SCAN_WIDTH), dtype=np.uint8)
        y0 = (SCAN_HEIGHT - nh) // 2
        x0 = (SCAN_WIDTH - nw) // 2
        canvas[y0 : y0 + nh, x0 : x0 + nw] = resized
        return canvas.tobytes()
    except ImportError:
        canvas = np.zeros((SCAN_HEIGHT, SCAN_WIDTH), dtype=np.uint8)
        # Aspect-correct letterbox via centered nearest sample.
        scale = min(SCAN_WIDTH / img.shape[1], SCAN_HEIGHT / img.shape[0])
        nw = max(1, round(img.shape[1] * scale))
        nh = max(1, round(img.shape[0] * scale))
        y0 = (SCAN_HEIGHT - nh) // 2
        x0 = (SCAN_WIDTH - nw) // 2
        yy = (np.linspace(0, img.shape[0] - 1, nh)).astype(np.int32)
        xx = (np.linspace(0, img.shape[1] - 1, nw)).astype(np.int32)
        canvas[y0 : y0 + nh, x0 : x0 + nw] = img[yy][:, xx]
        return canvas.tobytes()


class GT511C3Adapter:
    """UART adapter for GT-511C3 / GT-511C1R / compatible ADH modules."""

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        *,
        baud_rate: int = DEFAULT_BAUD,
        capture_timeout_s: float | None = None,
        upgrade_baud: bool = True,
        high_quality: bool = True,
    ):
        self._port = port
        self._baud_rate = int(baud_rate)
        self._capture_timeout_s = (
            _CAPTURE_TIMEOUT_S if capture_timeout_s is None else float(capture_timeout_s)
        )
        self._upgrade_baud = bool(upgrade_baud)
        self._high_quality = bool(high_quality)
        self._ser = None
        self._open = False

    @property
    def port(self) -> str:
        return self._port

    @property
    def connected(self) -> bool:
        return self._open and self._ser is not None

    def open(self) -> bool:
        try:
            import serial  # type: ignore
        except ImportError:
            logger.warning(
                "GT511C3Adapter: pyserial not installed "
                "(pip install 'driveauth-edge[finger]')"
            )
            return False
        if not Path(self._port).exists():
            logger.warning("GT511C3Adapter: port %s not found", self._port)
            return False
        try:
            self._ser = serial.Serial(
                port=self._port,
                baudrate=self._baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=_IO_TIMEOUT_S,
                write_timeout=_IO_TIMEOUT_S,
            )
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
            if not self._command(CMD_OPEN, 0):
                logger.error("GT511C3Adapter: Open failed on %s", self._port)
                self.close()
                return False
            if (
                self._upgrade_baud
                and self._baud_rate == DEFAULT_BAUD
                and self._change_baud(FAST_BAUD)
            ):
                self._baud_rate = FAST_BAUD
            # LED on so IsPressFinger / CaptureFinger work.
            self._command(CMD_CMOS_LED, 1)
            self._open = True
            logger.info(
                "GT511C3Adapter: opened on %s @ %d baud",
                self._port,
                self._baud_rate,
            )
            return True
        except Exception as exc:
            logger.error(
                "GT511C3Adapter: open failed on %s (%s)",
                self._port,
                type(exc).__name__,
            )
            self.close()
            return False

    def close(self) -> None:
        ser = self._ser
        was_open = self._open
        self._open = False
        if ser is None:
            return
        try:
            if was_open:
                try:
                    ser.write(build_command(CMD_CMOS_LED, 0))
                    ser.write(build_command(CMD_CLOSE, 0))
                    ser.flush()
                except Exception:
                    pass
            ser.close()
        except Exception:
            pass
        finally:
            self._ser = None

    def capture_image(self) -> bytes | None:
        if not self.connected:
            return None
        try:
            self._command(CMD_CMOS_LED, 1)
            deadline = time.monotonic() + max(0.5, self._capture_timeout_s)
            while time.monotonic() < deadline:
                pressed = self._is_press_finger()
                if pressed is True:
                    break
                if pressed is None:
                    return None
                time.sleep(0.05)
            else:
                logger.warning(
                    "GT511C3Adapter: finger press timed out after %.1fs",
                    self._capture_timeout_s,
                )
                return None

            if not self._command(CMD_CAPTURE_FINGER, 1 if self._high_quality else 0):
                logger.warning("GT511C3Adapter: CaptureFinger NACK")
                return None
            raw = self._get_image_bytes()
            if raw is None:
                return None
            out = resize_gt511_to_scan(raw)
            if out is None or len(out) != SCAN_BYTES:
                logger.warning("GT511C3Adapter: resize to %dx%d failed", SCAN_WIDTH, SCAN_HEIGHT)
                return None
            return out
        except Exception as exc:
            logger.warning("GT511C3Adapter: capture failed (%s)", type(exc).__name__)
            return None

    # ── protocol helpers ──────────────────────────────────────────────────

    def _change_baud(self, baud: int) -> bool:
        if not self._command(CMD_CHANGE_BAUD, int(baud)):
            return False
        try:
            assert self._ser is not None
            self._ser.baudrate = int(baud)
            time.sleep(0.05)
            self._ser.reset_input_buffer()
            return True
        except Exception:
            return False

    def _is_press_finger(self) -> bool | None:
        """True if pressed, False if not, None on comms failure."""
        result = self._command_raw(CMD_IS_PRESS_FINGER, 0)
        if result is None:
            return None
        ack, parameter, _ = result
        if not ack:
            return None
        # Datasheet / SparkFun: parameter == 0 → finger pressed.
        return int(parameter) == 0

    def _get_image_bytes(self) -> bytes | None:
        if not self._command(CMD_GET_IMAGE, 0):
            logger.warning("GT511C3Adapter: GetImage NACK")
            return None
        return self._read_data_payload(GT511_IMAGE_BYTES)

    def _command(self, command: int, parameter: int = 0) -> bool:
        result = self._command_raw(command, parameter)
        return bool(result and result[0])

    def _command_raw(
        self, command: int, parameter: int = 0
    ) -> tuple[bool, int, int] | None:
        ser = self._ser
        if ser is None:
            return None
        packet = build_command(command, parameter)
        try:
            ser.reset_input_buffer()
            ser.write(packet)
            ser.flush()
            buf = self._read_exact(12)
            if buf is None:
                return None
            parsed = parse_response(buf)
            if parsed is None:
                # Resync once: some bridges echo; scan for header.
                synced = self._resync_response(buf)
                if synced is None:
                    return None
                parsed = parse_response(synced)
            return parsed
        except Exception as exc:
            logger.warning(
                "GT511C3Adapter: command 0x%02x failed (%s)",
                command,
                type(exc).__name__,
            )
            return None

    def _resync_response(self, first: bytes) -> bytes | None:
        ser = self._ser
        if ser is None:
            return None
        window = bytearray(first)
        deadline = time.monotonic() + _IO_TIMEOUT_S
        while time.monotonic() < deadline and len(window) < 64:
            idx = bytes(window).find(_CMD_START)
            if idx >= 0 and len(window) - idx >= 12:
                return bytes(window[idx : idx + 12])
            chunk = ser.read(1)
            if not chunk:
                time.sleep(0.01)
                continue
            window.extend(chunk)
        idx = bytes(window).find(_CMD_START)
        if idx >= 0 and len(window) - idx >= 12:
            return bytes(window[idx : idx + 12])
        return None

    def _read_data_payload(self, nbytes: int) -> bytes | None:
        """Read a data packet (``0x5A 0xA5`` + device + payload + checksum)."""
        ser = self._ser
        if ser is None:
            return None
        # Header: start(2) + device(2)
        header = self._read_exact(4)
        if header is None:
            return None
        if header[0:2] != _DATA_START:
            # Some firmware streams bare pixels after ACK — accept if size matches.
            rest = self._read_exact(nbytes - 4)
            if rest is None:
                return None
            candidate = header + rest
            if len(candidate) == nbytes:
                return candidate
            logger.warning("GT511C3Adapter: bad data header %s", header[:4].hex())
            return None
        device = struct.unpack_from("<H", header, 2)[0]
        if device != _DEVICE_ID:
            logger.warning("GT511C3Adapter: unexpected device id 0x%04x", device)
        payload = self._read_exact(nbytes)
        if payload is None:
            return None
        # Trailing checksum (best-effort; some bridges drop it under load).
        _ = self._read_exact(2)
        return payload

    def _read_exact(self, n: int) -> bytes | None:
        ser = self._ser
        if ser is None or n <= 0:
            return None
        buf = bytearray()
        deadline = time.monotonic() + max(_IO_TIMEOUT_S, n / 8000.0 + 2.0)
        while len(buf) < n and time.monotonic() < deadline:
            chunk = ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
            else:
                time.sleep(0.005)
        if len(buf) != n:
            logger.warning(
                "GT511C3Adapter: short read (%d/%d bytes)", len(buf), n
            )
            return None
        return bytes(buf)


def probe_gt511(
    port: str | None = None,
    *,
    baud_rate: int | None = None,
) -> GT511C3Adapter | None:
    """Try to open a GT-511C3 on candidate UART ports."""
    from hardware.finger_uart import candidate_ports

    baud = DEFAULT_BAUD if baud_rate is None else int(baud_rate)
    env_baud = os.getenv("DRIVEAUTH_GT511_BAUD", "").strip()
    if env_baud.isdigit():
        baud = int(env_baud)

    for candidate in candidate_ports(port):
        adapter = GT511C3Adapter(candidate, baud_rate=baud)
        if adapter.open():
            return adapter
        adapter.close()
    return None
