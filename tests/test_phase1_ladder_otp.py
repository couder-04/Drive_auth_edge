"""Phase 1 — fingerprint daemon + Bluetooth ladder OTP."""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path

import numpy as np
import pytest

from driveauth import config
from driveauth.escalation import EscalationPolicy
from driveauth.matchers.mock import MockFaceMatcher, MockFingerMatcher, MockVoiceMatcher
from driveauth.step_up_otp import HTTPProviderDelivery, OTPStepUp
from driveauth.types import Decision
from hardware.bluetooth_otp import BluetoothOTPDelivery, normalize_mac
from hardware.finger_daemon import FingerDaemon
from hardware.finger_uart import ManualFingerSensor, SCAN_BYTES
from hardware.ladder_otp import LadderOTPLane
from testsupport import good_audio, make_auth, mature


# ── Finger daemon ────────────────────────────────────────────────────────────


def test_finger_daemon_scan_roundtrip():
    scan = bytes([i % 256 for i in range(SCAN_BYTES)])
    sensor = ManualFingerSensor(scan=scan)
    sock_path = str(Path(tempfile.mkdtemp()) / "finger.sock")
    daemon = FingerDaemon(sock_path, sensor)
    assert daemon.start() is True
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(sock_path)
        s.sendall(b"SCAN\n")
        chunks: list[bytes] = []
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
        s.close()
        got = b"".join(chunks)
        assert len(got) == SCAN_BYTES
        assert got == scan
    finally:
        daemon.stop()
    assert not Path(sock_path).exists()


def test_finger_daemon_reconnect_after_drop():
    sensor = ManualFingerSensor()
    sock_path = str(Path(tempfile.mkdtemp()) / "finger.sock")
    daemon = FingerDaemon(sock_path, sensor)
    assert daemon.start() is True
    assert daemon.sensor_ok is True
    sensor.close()
    daemon._sensor_ok = False
    assert daemon.reconnect_sensor() is True
    daemon.stop()


def test_finger_daemon_fails_closed_when_sensor_wont_open():
    class DeadSensor:
        def open(self) -> bool:
            return False

        def close(self) -> None:
            return None

        def capture_image(self) -> bytes | None:
            return None

    sock_path = str(Path(tempfile.mkdtemp()) / "finger.sock")
    daemon = FingerDaemon(sock_path, DeadSensor())  # type: ignore[arg-type]
    assert daemon.start() is False


# ── OTP delivery abstraction ─────────────────────────────────────────────────


class _RecordingDelivery:
    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls: list[tuple[str, str]] = []

    def deliver(self, mobile_number: str, code: str) -> bool:
        self.calls.append((mobile_number, code))
        return self.ok


@pytest.mark.parametrize("backend_name", ["http", "bluetooth", "recording"])
def test_otp_stepup_lifecycle_over_delivery_backends(backend_name, monkeypatch):
    captured: dict[str, str] = {}

    if backend_name == "http":

        def fake_urlopen(req, timeout=0):
            class Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            # Capture code from JSON body for verify.
            import json

            body = json.loads(req.data.decode())
            captured["code"] = body["code"]
            return Resp()

        monkeypatch.setattr(
            "urllib.request.urlopen",
            fake_urlopen,
        )
        otp = OTPStepUp(provider_url="http://example.test/otp")
    elif backend_name == "bluetooth":
        delivery = BluetoothOTPDelivery(
            registered_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
            paired_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
            map_send=lambda mac, payload: (
                captured.__setitem__("code", __import__("json").loads(payload)["code"])
                or True
            ),
            ble_send=lambda mac, payload: False,
        )
        otp = OTPStepUp(delivery=delivery)
    else:
        captured_box = captured

        class _Cap(_RecordingDelivery):
            def deliver(self, mobile_number: str, code: str) -> bool:
                captured_box["code"] = code
                return super().deliver(mobile_number, code)

        otp = OTPStepUp(delivery=_Cap(ok=True))

    ch = otp.send("+919999000000")
    assert ch is not None and ch.delivered
    assert otp.verify(captured["code"]) is True
    assert otp.has_active_challenge is False


def test_http_provider_delivery_unchanged_payment_path(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        import json

        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())

        class Resp:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    d = HTTPProviderDelivery("http://pay.test/otp")
    assert d.deliver("+91111", "654321") is True
    assert seen["body"]["purpose"] == "driveauth_step_up"
    assert seen["body"]["code"] == "654321"


def test_otp_payment_and_ladder_instances_do_not_share_state():
    pay = OTPStepUp(delivery=_RecordingDelivery())
    ladder = OTPStepUp(delivery=_RecordingDelivery())
    pay.create_local_challenge("111111")
    assert pay.has_active_challenge is True
    assert ladder.has_active_challenge is False
    ladder.create_local_challenge("222222")
    assert pay.verify("111111") is True
    assert ladder.verify("222222") is True


# ── Bluetooth delivery ───────────────────────────────────────────────────────


def test_bluetooth_otp_mac_mismatch_refuses():
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
        paired_mac_lookup=lambda: "11:22:33:44:55:66",
        map_send=lambda *_: True,
        ble_send=lambda *_: True,
    )
    assert delivery.deliver("+91999", "123456") is False


def test_bluetooth_otp_map_then_ble_fallback():
    calls: list[str] = []

    def map_send(mac, payload):
        calls.append("map")
        return False

    def ble_send(mac, payload):
        calls.append("ble")
        return True

    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=lambda: "aabbccddeeff",
        paired_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
        map_send=map_send,
        ble_send=ble_send,
    )
    assert delivery.deliver("+91999", "123456") is True
    assert calls == ["map", "ble"]
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"


def test_bluetooth_otp_both_fail_returns_false():
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
        paired_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
        map_send=lambda *_: False,
        ble_send=lambda *_: False,
    )
    assert delivery.deliver("+91999", "123456") is False


# ── Ladder stage-3 ───────────────────────────────────────────────────────────


def _wire_ladder_otp(auth, *, mac="AA:BB:CC:DD:EE:FF", paired=None, map_ok=True):
    contacts = Path(auth._store) / "contacts"
    contacts.mkdir(parents=True, exist_ok=True)
    (contacts / f"{auth.driver_id}.mobile").write_text("+919999000000\n")
    (contacts / f"{auth.driver_id}.bt_mac").write_text(mac + "\n")
    captured: dict[str, str] = {}
    paired_mac = paired if paired is not None else mac

    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=auth._registered_bt_mac,
        paired_mac_lookup=lambda: paired_mac,
        map_send=lambda _m, payload: (
            captured.__setitem__("code", __import__("json").loads(payload)["code"])
            or map_ok
        ),
        ble_send=lambda *_: False,
    )
    otp = OTPStepUp(delivery=delivery)
    lane = LadderOTPLane(
        otp=otp,
        mobile_lookup=auth._registered_mobile,
        registered_mac_lookup=auth._registered_bt_mac,
        code_provider=lambda: captured.get("code"),
    )
    auth._engine._ladder_otp = lane
    return captured


def test_ladder_plan_finger_only_default():
    pol = EscalationPolicy()
    plan = pol.plan(stage3_mode="finger_only")
    assert plan.order == ("voice", "face", "finger")
    assert plan.stage3_mode == "finger_only"
    assert "otp" not in plan.order


def test_ladder_plan_finger_or_otp_order():
    pol = EscalationPolicy()
    plan = pol.plan(stage3_mode="finger_or_otp", stage3_order=("finger", "otp"))
    assert plan.order == ("voice", "face", "finger", "otp")
    assert plan.reason == "voice_face_finger_or_otp_ladder"


def test_finger_or_otp_finger_pass(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    _wire_ladder_otp(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.95)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(audio_np=good_audio(), amount=100.0, beneficiary_known=True)
    assert r.decision == Decision.ACCEPT
    assert r.stage3_method == "finger"


def test_finger_or_otp_finger_unavailable_otp_pass(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    _wire_ladder_otp(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(audio_np=good_audio(), amount=100.0, beneficiary_known=True)
    assert r.decision == Decision.ACCEPT
    assert r.stage3_method == "otp_bluetooth"


def test_finger_or_otp_finger_fails_otp_pass(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    _wire_ladder_otp(auth)
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.20)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(audio_np=good_audio(), amount=100.0, beneficiary_known=True)
    assert r.decision == Decision.ACCEPT
    assert r.stage3_method == "otp_bluetooth"


def test_finger_or_otp_both_fail_reject(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    contacts = Path(auth._store) / "contacts"
    contacts.mkdir(parents=True, exist_ok=True)
    (contacts / f"{auth.driver_id}.mobile").write_text("+919999000000\n")
    (contacts / f"{auth.driver_id}.bt_mac").write_text("AA:BB:CC:DD:EE:FF\n")
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=auth._registered_bt_mac,
        paired_mac_lookup=lambda: "AA:BB:CC:DD:EE:FF",
        map_send=lambda *_: False,
        ble_send=lambda *_: False,
    )
    auth._engine._ladder_otp = LadderOTPLane(
        otp=OTPStepUp(delivery=delivery),
        mobile_lookup=auth._registered_mobile,
        registered_mac_lookup=auth._registered_bt_mac,
    )
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.finger = MockFingerMatcher(score=0.20)
    auth._engine._m.fingerprint_available = True
    r = auth.authenticate(audio_np=good_audio(), amount=100.0, beneficiary_known=True)
    assert r.decision == Decision.REJECT
    assert r.stage3_method is None


def test_finger_or_otp_mac_mismatch_otp_unavailable(monkeypatch):
    monkeypatch.setattr(config, "LADDER_STAGE3_MODE", "finger_or_otp")
    auth = make_auth()
    mature(auth)
    _wire_ladder_otp(auth, paired="11:22:33:44:55:66")
    auth._engine._m.voice = MockVoiceMatcher(score=0.40)
    auth._engine._m.face = MockFaceMatcher(score=0.40)
    auth._engine._m.fingerprint_available = False
    r = auth.authenticate(audio_np=good_audio(), amount=100.0, beneficiary_known=True)
    assert r.decision == Decision.REJECT
    assert r.stage3_method is None
    assert any("otp_unavailable" in e for e in r.explanations)


@pytest.mark.skipif(
    os.getenv("DRIVEAUTH_BT_HW_TEST", "0") != "1",
    reason="Real BlueZ/paired-phone test; set DRIVEAUTH_BT_HW_TEST=1",
)
def test_bluetooth_otp_real_hardware_gated():
    """Integration: requires a paired phone matching contacts/*.bt_mac."""
    from hardware.bluetooth_otp import default_paired_mac_lookup

    mac = default_paired_mac_lookup()
    assert mac is not None
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=lambda: mac,
        paired_mac_lookup=lambda: mac,
    )
    # Deliver a dummy code — fail-closed if MAP/BLE both absent.
    assert isinstance(delivery.deliver("+10000000000", "000000"), bool)
