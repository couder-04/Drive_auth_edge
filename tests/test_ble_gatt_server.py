"""Phase 9 — BLE GATT server (BlueZ mocked) + companion contract."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hardware.ble_gatt_server import (
    BLE_GATT_ACK_CHAR_UUID,
    BLE_GATT_OTP_CHAR_UUID,
    BLE_GATT_SERVICE_UUID,
    BleGattServer,
    BlueZBleGattBackend,
    MemoryBleGattBackend,
    encode_ack_payload,
    encode_otp_payload,
    parse_ack_payload,
    set_active_server,
)
from hardware.bluetooth_otp import BluetoothOTPDelivery, ble_gatt_push


@pytest.fixture(autouse=True)
def _clear_active_server():
    set_active_server(None)
    yield
    set_active_server(None)


def test_uuid_contract_nordic_uart_layout():
    assert BLE_GATT_SERVICE_UUID == "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
    assert BLE_GATT_OTP_CHAR_UUID == "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
    assert BLE_GATT_ACK_CHAR_UUID == "6e400002-b5a3-f393-e0a9-e50e24dcca9e"


def test_memory_server_push_otp_and_ack_roundtrip():
    backend = MemoryBleGattBackend()
    server = BleGattServer(backend=backend, prefer_bluez=False)
    assert server.start() is True
    assert server.running is True

    assert server.push_otp("654321", ttl_s=90) is True
    assert backend.last_notify is not None
    msg = json.loads(backend.last_notify.decode("utf-8"))
    assert msg["purpose"] == "driveauth_ladder_otp"
    assert msg["code"] == "654321"
    assert msg["ttl_s"] == 90

    backend.simulate_phone_ack(encode_ack_payload("654321", ok=True).encode("utf-8"))
    ack = server.wait_ack(timeout_s=0.5)
    assert ack is not None
    assert ack.ok is True
    assert ack.code == "654321"
    server.stop()
    assert server.running is False


def test_push_otp_fail_closed_when_not_started():
    server = BleGattServer(backend=MemoryBleGattBackend(), prefer_bluez=False)
    assert server.push_otp("111111") is False


def test_encode_parse_helpers():
    payload = encode_otp_payload("123456", ttl_s=120)
    assert '"code":"123456"' in payload
    ack = parse_ack_payload(encode_ack_payload("123456", ok=True))
    assert ack.ok and ack.code == "123456"
    bad = parse_ack_payload(b"not-json")
    assert bad.ok is False


def test_ble_gatt_push_prefers_active_local_server():
    backend = MemoryBleGattBackend()
    server = BleGattServer(backend=backend, prefer_bluez=False)
    server.start()
    payload = encode_otp_payload("999888")
    assert ble_gatt_push("AA:BB:CC:DD:EE:FF", payload) is True
    assert backend.last_notify == payload.encode("utf-8")
    server.stop()


def test_bluetooth_otp_delivery_uses_local_gatt_via_default_ble_send():
    backend = MemoryBleGattBackend()
    server = BleGattServer(backend=backend, prefer_bluez=False)
    server.start()
    mac = "AA:BB:CC:DD:EE:FF"
    delivery = BluetoothOTPDelivery(
        registered_mac_lookup=lambda: mac,
        paired_mac_lookup=lambda: mac,
        map_send=lambda _m, _p: False,  # force BLE path
    )
    assert delivery.deliver("unused", "424242") is True
    assert backend.last_notify is not None
    assert b"424242" in backend.last_notify
    server.stop()


def test_bluez_backend_fail_closed_without_dbus(monkeypatch):
    """BlueZ path must not raise when dbus/gi are absent."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "dbus" or name.startswith("dbus.") or name == "gi":
            raise ImportError("mocked missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = BlueZBleGattBackend()
    assert backend.start("DriveAuth-OTP") is False
    assert backend.notify_otp(b"x") is False


def test_bluez_backend_register_application_mocked():
    """Exercise BlueZ start path with dbus/gi fully mocked."""
    dbus = MagicMock()
    MagicMock()
    gi_repo = MagicMock()

    # Minimal dbus.service.Object so class bodies can decorate methods.
    class FakeObject:
        def __init__(self, bus, path):
            self.bus = bus
            self.path = path

    dbus.service = MagicMock()
    dbus.service.Object = FakeObject
    dbus.service.method = lambda *a, **k: (lambda f: f)
    dbus.service.signal = lambda *a, **k: (lambda f: f)
    dbus.Array = list
    dbus.Boolean = bool
    dbus.Byte = int
    dbus.ObjectPath = str
    dbus.SystemBus = MagicMock(return_value=MagicMock())
    dbus.Interface = MagicMock()
    dbus.mainloop = MagicMock()
    dbus.mainloop.glib = MagicMock()
    dbus.mainloop.glib.DBusGMainLoop = MagicMock()
    dbus.exceptions = MagicMock()
    dbus.exceptions.DBusException = Exception

    gi_repo.repository = MagicMock()
    gi_repo.repository.GLib = MagicMock()
    gi_repo.repository.GLib.MainLoop = MagicMock(return_value=MagicMock())

    with patch.dict(
        "sys.modules",
        {
            "dbus": dbus,
            "dbus.service": dbus.service,
            "dbus.mainloop": dbus.mainloop,
            "dbus.mainloop.glib": dbus.mainloop.glib,
            "dbus.exceptions": dbus.exceptions,
            "gi": gi_repo,
            "gi.repository": gi_repo.repository,
        },
    ):
        backend = BlueZBleGattBackend(adapter_path="/org/bluez/hci0")
        # RegisterApplication / RegisterAdvertisement succeed via MagicMock
        ok = backend.start("DriveAuth-OTP")
        assert ok is True
        # PropertiesChanged signalling needs a real dbus service; stub the
        # characteristic notify path so we assert the backend wiring only.
        assert backend._otp_char is not None
        backend._otp_char.send_notify = MagicMock(return_value=True)
        assert backend.notify_otp(b'{"v":1}') is True
        backend._otp_char.send_notify.assert_called_once_with(b'{"v":1}')
        backend.stop()
