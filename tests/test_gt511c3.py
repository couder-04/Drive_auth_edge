"""Unit tests for GT-511C3 packet codec + scan resize (no UART required)."""

from __future__ import annotations

import struct

import numpy as np
import pytest
from hardware.finger_uart import SCAN_BYTES, ManualFingerSensor, open_default_sensor
from hardware.gt511c3 import (
    CMD_ACK,
    CMD_CMOS_LED,
    CMD_OPEN,
    GT511_IMAGE_BYTES,
    GT511_IMAGE_H,
    GT511_IMAGE_W,
    GT511C3Adapter,
    build_command,
    parse_response,
    resize_gt511_to_scan,
)


def test_build_command_checksum_led_on():
    # Known SparkFun / Processing LED-on packet.
    pkt = build_command(CMD_CMOS_LED, 1)
    assert len(pkt) == 12
    assert pkt[0:2] == b"\x55\xaa"
    assert pkt[8] == CMD_CMOS_LED
    assert sum(pkt[:10]) & 0xFFFF == struct.unpack_from("<H", pkt, 10)[0]
    assert pkt == bytes(
        [0x55, 0xAA, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x12, 0x00, 0x13, 0x01]
    )


def test_build_command_open():
    pkt = build_command(CMD_OPEN, 0)
    assert len(pkt) == 12
    assert pkt[8] == CMD_OPEN
    assert struct.unpack_from("<H", pkt, 10)[0] == (sum(pkt[:10]) & 0xFFFF)


def test_parse_ack_response():
    body = bytes([0x55, 0xAA, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, CMD_ACK, 0x00])
    pkt = body + struct.pack("<H", sum(body) & 0xFFFF)
    parsed = parse_response(pkt)
    assert parsed is not None
    ack, parameter, code = parsed
    assert ack is True
    assert parameter == 0
    assert code == CMD_ACK


def test_parse_nack_response():
    # NACK finger not pressed 0x1012 in parameter (LE).
    body = bytes([0x55, 0xAA, 0x01, 0x00, 0x12, 0x10, 0x00, 0x00, 0x31, 0x00])
    pkt = body + struct.pack("<H", sum(body) & 0xFFFF)
    parsed = parse_response(pkt)
    assert parsed is not None
    ack, parameter, _ = parsed
    assert ack is False
    assert parameter == 0x1012


def test_parse_bad_checksum():
    body = bytes([0x55, 0xAA, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, CMD_ACK, 0x00])
    pkt = body + b"\x00\x00"
    assert parse_response(pkt) is None


def test_resize_gt511_to_scan_bytes():
    raw = bytes([120]) * GT511_IMAGE_BYTES
    out = resize_gt511_to_scan(raw)
    assert out is not None
    assert len(out) == SCAN_BYTES


def test_resize_gt511_to_scan_array():
    img = np.full((GT511_IMAGE_H, GT511_IMAGE_W), 90, dtype=np.uint8)
    out = resize_gt511_to_scan(img)
    assert out is not None
    assert len(out) == SCAN_BYTES
    arr = np.frombuffer(out, dtype=np.uint8).reshape(256, 256)
    # Letterboxed image should be mostly mid-gray in the center band.
    assert int(arr[128, 128]) == 90


def test_resize_rejects_short():
    assert resize_gt511_to_scan(b"\x00\x01\x02") is None


def test_gt511_open_missing_port(tmp_path):
    adapter = GT511C3Adapter(str(tmp_path / "no-tty"))
    assert adapter.open() is False
    assert adapter.connected is False


def test_gt511_open_without_pyserial(monkeypatch, tmp_path):
    port = tmp_path / "fake"
    port.write_text("")
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "serial" or name.startswith("serial."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    adapter = GT511C3Adapter(str(port))
    assert adapter.open() is False


def test_open_default_prefers_gt511_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIVEAUTH_FINGER_SENSOR", "gt511")
    monkeypatch.setenv("DRIVEAUTH_FINGER_UART", str(tmp_path / "missing"))
    sensor, kind = open_default_sensor(allow_manual_fallback=True)
    assert kind == "manual_fallback"
    assert isinstance(sensor, ManualFingerSensor)


def test_open_default_gt511_no_fallback_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIVEAUTH_FINGER_SENSOR", "gt511")
    monkeypatch.setenv("DRIVEAUTH_FINGER_UART", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="GT-511C3"):
        open_default_sensor(allow_manual_fallback=False)
