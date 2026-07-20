"""Bluetooth OTP delivery for the identity-ladder stage-3 lane.

**Not** the payment ``otp_mobile`` HTTP path — that stays on
``HTTPProviderDelivery``. This module pushes a short code to the driver's
already-paired phone over the head-unit Bluetooth radio.

Delivery order
--------------
1. **MAP** (Message Access Profile) via BlueZ — arrives as an SMS-style
   notification when the phone grants messaging access.
2. **BLE GATT** fallback — car-side ``BleGattServer`` notifies the companion
   PWA (or legacy central-write to a remote characteristic if no local
   server is running).

Companion-app BLE contract
--------------------------
* Service UUID: ``BLE_GATT_SERVICE_UUID``
* OTP notify UUID: ``BLE_GATT_CHAR_UUID`` / ``BLE_GATT_OTP_CHAR_UUID``
  (car → phone)
* Ack write UUID: ``BLE_GATT_ACK_CHAR_UUID`` (phone → car)
* Payload (UTF-8 JSON, ≤ 180 bytes)::

    {"v":1,"purpose":"driveauth_ladder_otp","code":"123456","ttl_s":120}

Reference implementation: ``hardware/ble_gatt_server.py`` +
``companion/ble_otp_pwa/``. See ``docs/integration.md``.

Security: never deliver to whatever phone is paired — the paired MAC must
match ``contacts/{driver_id}.bt_mac`` (or the configured lookup).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from driveauth import config

logger = logging.getLogger("driveauth.hardware.bluetooth_otp")

# Fixed UUIDs for the companion-app GATT contract (keep in sync with
# hardware.ble_gatt_server and companion/ble_otp_pwa).
BLE_GATT_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_GATT_OTP_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
BLE_GATT_ACK_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
BLE_GATT_CHAR_UUID = BLE_GATT_OTP_CHAR_UUID  # back-compat alias

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}([:-]?)){5}[0-9A-Fa-f]{2}$")


def normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    cleaned = mac.strip().upper().replace("-", ":")
    if not _MAC_RE.match(cleaned.replace(":", "")) and not _MAC_RE.match(
        mac.strip()
    ):
        # Accept both AA:BB:... and AABBCCDDEEFF after normalization.
        hex_only = re.sub(r"[^0-9A-Fa-f]", "", mac)
        if len(hex_only) != 12:
            return None
        cleaned = ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).upper()
    else:
        hex_only = re.sub(r"[^0-9A-Fa-f]", "", cleaned)
        if len(hex_only) != 12:
            return None
        cleaned = ":".join(hex_only[i : i + 2] for i in range(0, 12, 2)).upper()
    return cleaned


class BluetoothOTPDelivery:
    """``OTPDelivery`` backend: MAP first, then BLE GATT. Never raises to caller."""

    def __init__(
        self,
        *,
        registered_mac_lookup: Callable[[], str | None],
        paired_mac_lookup: Callable[[], str | None] | None = None,
        map_send: Callable[[str, str], bool] | None = None,
        ble_send: Callable[[str, str], bool] | None = None,
    ):
        self._registered_mac_lookup = registered_mac_lookup
        self._paired_mac_lookup = paired_mac_lookup or default_paired_mac_lookup
        self._map_send = map_send or map_push_message
        self._ble_send = ble_send or ble_gatt_push

    def deliver(self, mobile_number: str, code: str) -> bool:
        try:
            registered = normalize_mac(self._registered_mac_lookup())
            paired = normalize_mac(self._paired_mac_lookup())
            if not registered or not paired or registered != paired:
                logger.warning(
                    "BT OTP: refusing delivery — registered/paired MAC mismatch "
                    "(reg=%s paired=%s)",
                    registered,
                    paired,
                )
                return False
            payload = _ladder_payload(code)
            if self._map_send(paired, payload):
                logger.info("BT OTP: delivered via MAP to %s", paired)
                return True
            if self._ble_send(paired, payload):
                logger.info("BT OTP: delivered via BLE GATT to %s", paired)
                return True
            logger.warning("BT OTP: MAP and BLE GATT both unavailable for %s", paired)
            return False
        except Exception as exc:
            logger.warning("BT OTP: delivery failed (%s)", type(exc).__name__)
            return False


def _ladder_payload(code: str) -> str:
    return json.dumps(
        {
            "v": 1,
            "purpose": "driveauth_ladder_otp",
            "code": code,
            "ttl_s": int(config.OTP_TTL_S),
        },
        separators=(",", ":"),
    )


def default_paired_mac_lookup() -> str | None:
    """Best-effort: currently connected BlueZ device used for HFP."""
    try:
        return _bluez_connected_mac()
    except Exception as exc:
        logger.info("BT OTP: paired MAC lookup failed (%s)", type(exc).__name__)
        return None


def map_push_message(mac: str, payload: str) -> bool:
    """Push via Message Access Profile. Returns False if MAP unavailable."""
    try:
        return _bluez_map_send(mac, payload)
    except Exception as exc:
        logger.info("BT OTP: MAP send failed (%s)", type(exc).__name__)
        return False


def ble_gatt_push(mac: str, payload: str) -> bool:
    """Notify companion app over BLE GATT. Returns False if link unavailable.

    Prefers a running car-side ``BleGattServer`` (Phase 9). Falls back to the
    legacy central-write path against a remote characteristic.
    """
    try:
        from hardware.ble_gatt_server import get_active_server

        server = get_active_server()
        if server is not None and server.running:
            return bool(server.push_payload(payload))
    except Exception as exc:
        logger.info("BT OTP: local GATT server push failed (%s)", type(exc).__name__)
    try:
        return _bluez_ble_notify(mac, payload)
    except Exception as exc:
        logger.info("BT OTP: BLE GATT send failed (%s)", type(exc).__name__)
        return False


def _bluez_connected_mac() -> str | None:
    """Query BlueZ over D-Bus for a connected device (HFP reuse)."""
    try:
        import dbus  # type: ignore
    except ImportError:
        return None
    bus = dbus.SystemBus()
    mgr = dbus.Interface(
        bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
    )
    objects = mgr.GetManagedObjects()
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Device1")
        if not props:
            continue
        if not bool(props.get("Connected", False)):
            continue
        addr = str(props.get("Address", "") or "")
        mac = normalize_mac(addr)
        if mac:
            return mac
    return None


def _bluez_map_send(mac: str, payload: str) -> bool:
    """
    Minimal MAP push via BlueZ message client.

    Full MAP client setup is head-unit specific; this tries the common
    ``org.bluez.obex`` message API and returns False when absent so the
    BLE GATT fallback can run.
    """
    try:
        import dbus  # type: ignore
    except ImportError:
        return False
    # Presence check only — real OBEX MAP session wiring varies by stack.
    bus = dbus.SessionBus()
    try:
        bus.get_object("org.bluez.obex", "/")
    except dbus.exceptions.DBusException:
        return False
    # Without a full MAP agent on the head unit we cannot complete the push.
    # Returning False triggers BLE GATT fallback (fail-closed for MAP).
    logger.info("BT OTP: BlueZ OBEX present but MAP agent not configured for %s", mac)
    return False


def _bluez_ble_notify(mac: str, payload: str) -> bool:
    """Legacy: write the companion characteristic if the phone is a peripheral."""
    try:
        import dbus  # type: ignore
    except ImportError:
        return False
    bus = dbus.SystemBus()
    mgr = dbus.Interface(
        bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
    )
    objects = mgr.GetManagedObjects()
    target = normalize_mac(mac)
    device_path = None
    for path, ifaces in objects.items():
        props = ifaces.get("org.bluez.Device1")
        if not props:
            continue
        if normalize_mac(str(props.get("Address", "") or "")) == target:
            device_path = path
            break
    if device_path is None:
        return False
    char_path = None
    for path, ifaces in objects.items():
        if not str(path).startswith(str(device_path)):
            continue
        props = ifaces.get("org.bluez.GattCharacteristic1")
        if not props:
            continue
        uuid = str(props.get("UUID", "") or "").lower()
        if uuid == BLE_GATT_CHAR_UUID.lower():
            char_path = path
            break
    if char_path is None:
        return False
    char = dbus.Interface(
        bus.get_object("org.bluez", char_path), "org.bluez.GattCharacteristic1"
    )
    data = list(payload.encode("utf-8"))
    char.WriteValue(data, {})
    return True
