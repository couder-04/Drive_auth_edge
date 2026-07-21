"""Unit tests for R307/AS608 UART adapter selection + scan normalization."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hardware.finger_uart import (
    AS608Adapter,
    ManualFingerSensor,
    PyFingerprintAdapter,
    R307Adapter,
    SCAN_BYTES,
    _normalize_scan_bytes,
    candidate_ports,
    open_default_sensor,
)
from testsupport_afunix import requires_af_unix


def test_aliases_are_pyfingerprint_adapter():
    assert R307Adapter is PyFingerprintAdapter
    assert AS608Adapter is PyFingerprintAdapter


def test_normalize_pads_short_scans():
    raw = bytes([1, 2, 3, 4])
    out = _normalize_scan_bytes(raw)
    assert out is not None
    assert len(out) == SCAN_BYTES
    assert out[:4] == raw


def test_normalize_truncates_long_scans():
    raw = bytes([7]) * (SCAN_BYTES + 50)
    out = _normalize_scan_bytes(raw)
    assert out is not None
    assert len(out) == SCAN_BYTES


def test_normalize_list_payload():
    out = _normalize_scan_bytes([10, 20, 30])
    assert out is not None and len(out) == SCAN_BYTES


def test_normalize_none():
    assert _normalize_scan_bytes(None) is None
    assert _normalize_scan_bytes([]) is None


def test_manual_sensor_roundtrip():
    scan = bytes([42]) * SCAN_BYTES
    sensor = ManualFingerSensor(scan=scan)
    assert sensor.open() is True
    assert sensor.capture_image() == scan
    sensor.close()
    assert sensor.capture_image() is None


def test_candidate_ports_prefers_env(monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_FINGER_UART", "/dev/ttyUSB9")
    ports = candidate_ports("/dev/custom")
    assert ports[0] == "/dev/custom"
    assert ports[1] == "/dev/ttyUSB9"


def test_open_default_manual_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DRIVEAUTH_FINGER_MANUAL", "1")
    sensor, kind = open_default_sensor()
    assert kind == "manual"
    assert isinstance(sensor, ManualFingerSensor)


def test_open_default_falls_back_without_uart(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DRIVEAUTH_FINGER_MANUAL", raising=False)
    monkeypatch.setenv("DRIVEAUTH_FINGER_UART", str(tmp_path / "missing-port"))
    sensor, kind = open_default_sensor(allow_manual_fallback=True)
    assert kind == "manual_fallback"
    assert isinstance(sensor, ManualFingerSensor)


def test_open_default_no_fallback_raises(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("DRIVEAUTH_FINGER_MANUAL", raising=False)
    monkeypatch.setenv("DRIVEAUTH_FINGER_UART", str(tmp_path / "missing-port"))
    with pytest.raises(RuntimeError, match="No fingerprint"):
        open_default_sensor(allow_manual_fallback=False)


def test_pyfingerprint_open_missing_port(tmp_path: Path):
    adapter = PyFingerprintAdapter(str(tmp_path / "no-such-tty"))
    assert adapter.open() is False
    assert adapter.connected is False


def test_pyfingerprint_open_without_sdk(monkeypatch, tmp_path: Path):
    port = tmp_path / "fake"
    port.write_text("")
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "pyfingerprint" or name.startswith("pyfingerprint."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    adapter = PyFingerprintAdapter(str(port))
    assert adapter.open() is False


@requires_af_unix
def test_daemon_uses_open_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DRIVEAUTH_FINGER_MANUAL", "1")
    from hardware.finger_daemon import FingerDaemon

    sensor, kind = open_default_sensor()
    # AF_UNIX paths are capped (~104 bytes on macOS); keep the socket short.
    sock = f"/tmp/driveauth_finger_test_{os.getpid()}.sock"
    daemon = FingerDaemon(sock, sensor, sensor_kind=kind)
    assert daemon.sensor_kind == "manual"
    try:
        assert daemon.start() is True
    finally:
        daemon.stop()
