"""Car-side BLE GATT peripheral for ladder OTP (BlueZ D-Bus).

Roles (Nordic UART–style UUID layout, fixed contract)
----------------------------------------------------
* Service ``BLE_GATT_SERVICE_UUID``
* Notify characteristic ``BLE_GATT_OTP_CHAR_UUID`` (``BLE_GATT_CHAR_UUID``):
  car → phone OTP push (phone subscribes / Web Bluetooth ``startNotifications``)
* Write characteristic ``BLE_GATT_ACK_CHAR_UUID``:
  phone → car ack (UTF-8 JSON)

Payload (UTF-8 JSON, ≤ 180 bytes)::

    {"v":1,"purpose":"driveauth_ladder_otp","code":"123456","ttl_s":120}

Ack (UTF-8 JSON)::

    {"v":1,"purpose":"driveauth_ladder_otp_ack","code":"123456","ok":true}

Default backend is BlueZ over D-Bus when ``dbus`` / PyGObject are available;
otherwise use ``MemoryBleGattBackend`` (unit tests / hosts without BlueZ).
Inject ``backend`` to mock BlueZ entirely. Fail-closed: ``start()`` /
``push_otp()`` return False when the radio path is unavailable — never
raise to callers.

See ``docs/integration.md`` for UUIDs and the phone-side manual checklist.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from driveauth import config

logger = logging.getLogger("driveauth.hardware.ble_gatt")

# Fixed UUIDs — keep in sync with hardware.bluetooth_otp and the companion PWA.
BLE_GATT_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_GATT_OTP_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify
BLE_GATT_ACK_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write
# Back-compat alias used by bluetooth_otp / older docs.
BLE_GATT_CHAR_UUID = BLE_GATT_OTP_CHAR_UUID

LOCAL_NAME_DEFAULT = "DriveAuth-OTP"

_ACTIVE: BleGattServer | None = None
_ACTIVE_LOCK = threading.Lock()


@dataclass(frozen=True)
class AckMessage:
    ok: bool
    code: str | None
    raw: str


@runtime_checkable
class BleGattBackend(Protocol):
    def start(self, local_name: str) -> bool: ...
    def stop(self) -> None: ...
    def notify_otp(self, payload: bytes) -> bool: ...
    def set_ack_handler(self, handler: Callable[[bytes], None] | None) -> None: ...


class MemoryBleGattBackend:
    """In-process stand-in — no BlueZ. Used by unit tests and dbus-less hosts."""

    def __init__(self) -> None:
        self._started = False
        self._ack_handler: Callable[[bytes], None] | None = None
        self.last_notify: bytes | None = None
        self.local_name: str = ""

    def start(self, local_name: str) -> bool:
        self._started = True
        self.local_name = local_name
        return True

    def stop(self) -> None:
        self._started = False

    def notify_otp(self, payload: bytes) -> bool:
        if not self._started:
            return False
        self.last_notify = bytes(payload)
        return True

    def set_ack_handler(self, handler: Callable[[bytes], None] | None) -> None:
        self._ack_handler = handler

    def simulate_phone_ack(self, payload: bytes) -> None:
        """Test helper: phone writes the ack characteristic."""
        if self._ack_handler is not None:
            self._ack_handler(payload)


class BlueZBleGattBackend:
    """
    Peripheral GATT application via BlueZ SystemBus.

    Requires ``dbus-python``, PyGObject (``gi``), and a BlueZ stack with LE
    support. Failures return False (fail-closed) rather than raising.
    """

    def __init__(self, adapter_path: str = "/org/bluez/hci0") -> None:
        self._adapter_path = adapter_path
        self._ack_handler: Callable[[bytes], None] | None = None
        self._bus: Any = None
        self._app: Any = None
        self._adv: Any = None
        self._otp_char: Any = None
        self._mainloop: Any = None
        self._thread: threading.Thread | None = None
        self._started = False

    def set_ack_handler(self, handler: Callable[[bytes], None] | None) -> None:
        self._ack_handler = handler

    def start(self, local_name: str) -> bool:
        try:
            import dbus  # type: ignore
            import dbus.mainloop.glib  # type: ignore
            from gi.repository import GLib  # type: ignore
        except ImportError as exc:
            logger.info("BLE GATT: BlueZ deps missing (%s)", type(exc).__name__)
            return False
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SystemBus()
            self._mainloop = GLib.MainLoop()

            app = _GattApplication(self._bus, self._on_ack_bytes)
            self._app = app
            self._otp_char = app.otp_char

            gatt_mgr = dbus.Interface(
                self._bus.get_object("org.bluez", self._adapter_path),
                "org.bluez.GattManager1",
            )
            gatt_mgr.RegisterApplication(
                app.get_path(),
                {},
                reply_handler=lambda: None,
                error_handler=lambda e: logger.warning(
                    "BLE GATT: RegisterApplication failed: %s", e
                ),
            )

            adv = _Advertisement(self._bus, local_name)
            self._adv = adv
            ad_mgr = dbus.Interface(
                self._bus.get_object("org.bluez", self._adapter_path),
                "org.bluez.LEAdvertisingManager1",
            )
            ad_mgr.RegisterAdvertisement(
                adv.get_path(),
                {},
                reply_handler=lambda: None,
                error_handler=lambda e: logger.warning(
                    "BLE GATT: RegisterAdvertisement failed: %s", e
                ),
            )

            self._thread = threading.Thread(
                target=self._mainloop.run, name="ble-gatt-glib", daemon=True
            )
            self._thread.start()
            self._started = True
            logger.info("BLE GATT: advertising as %s", local_name)
            return True
        except Exception as exc:
            logger.warning("BLE GATT: BlueZ start failed (%s)", type(exc).__name__)
            self.stop()
            return False

    def stop(self) -> None:
        try:
            if self._bus is not None and self._adapter_path:
                import dbus  # type: ignore

                if self._adv is not None:
                    try:
                        ad_mgr = dbus.Interface(
                            self._bus.get_object("org.bluez", self._adapter_path),
                            "org.bluez.LEAdvertisingManager1",
                        )
                        ad_mgr.UnregisterAdvertisement(self._adv.get_path())
                    except Exception:
                        pass
                if self._app is not None:
                    try:
                        gatt_mgr = dbus.Interface(
                            self._bus.get_object("org.bluez", self._adapter_path),
                            "org.bluez.GattManager1",
                        )
                        gatt_mgr.UnregisterApplication(self._app.get_path())
                    except Exception:
                        pass
        finally:
            if self._mainloop is not None:
                try:
                    self._mainloop.quit()
                except Exception:
                    pass
            self._started = False
            self._bus = None
            self._app = None
            self._adv = None
            self._otp_char = None

    def notify_otp(self, payload: bytes) -> bool:
        if not self._started or self._otp_char is None:
            return False
        try:
            return bool(self._otp_char.send_notify(payload))
        except Exception as exc:
            logger.warning("BLE GATT: notify failed (%s)", type(exc).__name__)
            return False

    def _on_ack_bytes(self, data: bytes) -> None:
        if self._ack_handler is not None:
            self._ack_handler(data)


def _dbus_array(data: bytes):
    import dbus  # type: ignore

    return dbus.Array([dbus.Byte(b) for b in data], signature="y")


class _Advertisement:
    """Minimal ``org.bluez.LEAdvertisement1``."""

    PATH = "/com/driveauth/ble/advertisement0"

    def __init__(self, bus: Any, local_name: str) -> None:
        import dbus  # type: ignore
        import dbus.service  # type: ignore

        self._local_name = local_name

        class Adv(dbus.service.Object):
            def __init__(inner_self):
                dbus.service.Object.__init__(inner_self, bus, _Advertisement.PATH)

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="ss",
                out_signature="v",
            )
            def Get(inner_self, interface, prop):
                return inner_self.GetAll(interface)[prop]

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="s",
                out_signature="a{sv}",
            )
            def GetAll(inner_self, interface):
                if interface != "org.bluez.LEAdvertisement1":
                    raise dbus.exceptions.DBusException("invalid iface")
                return {
                    "Type": "peripheral",
                    "ServiceUUIDs": dbus.Array(
                        [BLE_GATT_SERVICE_UUID], signature="s"
                    ),
                    "LocalName": self._local_name,
                    "IncludeTxPower": dbus.Boolean(True),
                }

            @dbus.service.method(
                "org.bluez.LEAdvertisement1", in_signature="", out_signature=""
            )
            def Release(inner_self):
                pass

        self._obj = Adv()

    def get_path(self) -> str:
        return self.PATH


class _GattApplication:
    PATH = "/com/driveauth/ble/app"

    def __init__(self, bus: Any, on_ack: Callable[[bytes], None]) -> None:
        import dbus.service  # type: ignore

        self.otp_char: _OtpCharacteristic | None = None
        parent = self

        class Application(dbus.service.Object):
            def __init__(inner_self):
                inner_self._services: list = []
                dbus.service.Object.__init__(
                    inner_self, bus, _GattApplication.PATH
                )
                svc = _GattService(bus, 0, on_ack)
                inner_self._services.append(svc)
                parent.otp_char = svc.otp_char

            @dbus.service.method(
                "org.freedesktop.DBus.ObjectManager",
                out_signature="a{oa{sa{sv}}}",
            )
            def GetManagedObjects(inner_self):
                out: dict = {}
                for svc in inner_self._services:
                    out[svc.get_path()] = svc.get_properties()
                    for char in svc.chars:
                        out[char.get_path()] = char.get_properties()
                return out

        self._obj = Application()

    def get_path(self) -> str:
        return self.PATH


class _GattService:
    def __init__(self, bus: Any, index: int, on_ack: Callable[[bytes], None]) -> None:
        import dbus.service  # type: ignore

        self.path = f"/com/driveauth/ble/app/service{index}"
        self.chars: list = []

        class Service(dbus.service.Object):
            def __init__(inner_self):
                dbus.service.Object.__init__(inner_self, bus, self.path)

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="ss",
                out_signature="v",
            )
            def Get(inner_self, interface, prop):
                return inner_self.GetAll(interface)[prop]

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="s",
                out_signature="a{sv}",
            )
            def GetAll(inner_self, interface):
                return self.get_properties()[interface]

        self._obj = Service()
        self.otp_char = _OtpCharacteristic(bus, self.path, 0)
        self.ack_char = _AckCharacteristic(bus, self.path, 1, on_ack)
        self.chars = [self.otp_char, self.ack_char]

    def get_path(self) -> str:
        return self.path

    def get_properties(self) -> dict:
        import dbus  # type: ignore

        return {
            "org.bluez.GattService1": {
                "UUID": BLE_GATT_SERVICE_UUID,
                "Primary": dbus.Boolean(True),
                "Characteristics": dbus.Array(
                    [c.get_path() for c in self.chars], signature="o"
                ),
            }
        }


class _OtpCharacteristic:
    """Notify-only OTP characteristic (car → phone)."""

    def __init__(self, bus: Any, service_path: str, index: int) -> None:
        import dbus.service  # type: ignore

        self.path = f"{service_path}/char{index}"
        self._value = bytes()
        self._notifying = False
        service_obj_path = service_path

        class Char(dbus.service.Object):
            def __init__(inner_self):
                dbus.service.Object.__init__(inner_self, bus, self.path)

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="ss",
                out_signature="v",
            )
            def Get(inner_self, interface, prop):
                return inner_self.GetAll(interface)[prop]

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="s",
                out_signature="a{sv}",
            )
            def GetAll(inner_self, interface):
                return self.get_properties()[interface]

            @dbus.service.method(
                "org.bluez.GattCharacteristic1",
                in_signature="a{sv}",
                out_signature="ay",
            )
            def ReadValue(inner_self, options):
                return _dbus_array(self._value)

            @dbus.service.method(
                "org.bluez.GattCharacteristic1",
                in_signature="",
                out_signature="",
            )
            def StartNotify(inner_self):
                self._notifying = True

            @dbus.service.method(
                "org.bluez.GattCharacteristic1",
                in_signature="",
                out_signature="",
            )
            def StopNotify(inner_self):
                self._notifying = False

            @dbus.service.signal(
                "org.freedesktop.DBus.Properties", signature="sa{sv}as"
            )
            def PropertiesChanged(inner_self, interface, changed, invalidated):
                pass

        self._obj = Char()
        self._service_path = service_obj_path
        self._PropertiesChanged = self._obj.PropertiesChanged

    def get_path(self) -> str:
        return self.path

    def get_properties(self) -> dict:
        import dbus  # type: ignore

        return {
            "org.bluez.GattCharacteristic1": {
                "UUID": BLE_GATT_OTP_CHAR_UUID,
                "Service": dbus.ObjectPath(self._service_path),
                "Flags": dbus.Array(["read", "notify"], signature="s"),
                "Value": _dbus_array(self._value),
            }
        }

    def send_notify(self, payload: bytes) -> bool:
        self._value = bytes(payload)
        if not self._notifying:
            logger.info("BLE GATT: OTP value set (no subscriber yet)")
        try:
            self._PropertiesChanged(
                "org.bluez.GattCharacteristic1",
                {"Value": _dbus_array(self._value)},
                [],
            )
            return True
        except Exception as exc:
            logger.warning(
                "BLE GATT: PropertiesChanged failed (%s)", type(exc).__name__
            )
            return False


class _AckCharacteristic:
    """Write-only ack characteristic (phone → car)."""

    def __init__(
        self, bus: Any, service_path: str, index: int, on_ack: Callable[[bytes], None]
    ) -> None:
        import dbus.service  # type: ignore

        self.path = f"{service_path}/char{index}"
        self._on_ack = on_ack
        self._service_path = service_path

        class Char(dbus.service.Object):
            def __init__(inner_self):
                dbus.service.Object.__init__(inner_self, bus, self.path)

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="ss",
                out_signature="v",
            )
            def Get(inner_self, interface, prop):
                return inner_self.GetAll(interface)[prop]

            @dbus.service.method(
                "org.freedesktop.DBus.Properties",
                in_signature="s",
                out_signature="a{sv}",
            )
            def GetAll(inner_self, interface):
                return self.get_properties()[interface]

            @dbus.service.method(
                "org.bluez.GattCharacteristic1",
                in_signature="aya{sv}",
                out_signature="",
            )
            def WriteValue(inner_self, value, options):
                data = bytes(int(b) for b in value)
                self._on_ack(data)

        self._obj = Char()

    def get_path(self) -> str:
        return self.path

    def get_properties(self) -> dict:
        import dbus  # type: ignore

        return {
            "org.bluez.GattCharacteristic1": {
                "UUID": BLE_GATT_ACK_CHAR_UUID,
                "Service": dbus.ObjectPath(self._service_path),
                "Flags": dbus.Array(
                    ["write", "write-without-response"], signature="s"
                ),
            }
        }


def encode_otp_payload(code: str, ttl_s: int | None = None) -> str:
    return json.dumps(
        {
            "v": 1,
            "purpose": "driveauth_ladder_otp",
            "code": code,
            "ttl_s": int(config.OTP_TTL_S if ttl_s is None else ttl_s),
        },
        separators=(",", ":"),
    )


def parse_ack_payload(raw: bytes | str) -> AckMessage:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return AckMessage(ok=False, code=None, raw=text)
        return AckMessage(
            ok=bool(data.get("ok", False)),
            code=str(data["code"]) if data.get("code") is not None else None,
            raw=text,
        )
    except Exception:
        return AckMessage(ok=False, code=None, raw=text)


def encode_ack_payload(code: str, *, ok: bool = True) -> str:
    return json.dumps(
        {
            "v": 1,
            "purpose": "driveauth_ladder_otp_ack",
            "code": code,
            "ok": bool(ok),
        },
        separators=(",", ":"),
    )


class BleGattServer:
    """Car-side GATT peripheral: push OTP notify, receive phone ack."""

    def __init__(
        self,
        *,
        backend: BleGattBackend | None = None,
        local_name: str = LOCAL_NAME_DEFAULT,
        prefer_bluez: bool = True,
    ):
        if backend is not None:
            self._backend = backend
        elif prefer_bluez:
            self._backend = BlueZBleGattBackend()
        else:
            self._backend = MemoryBleGattBackend()
        self._local_name = local_name
        self._running = False
        self._last_ack: AckMessage | None = None
        self._ack_event = threading.Event()
        self._backend.set_ack_handler(self._on_ack)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_ack(self) -> AckMessage | None:
        return self._last_ack

    @property
    def backend(self) -> BleGattBackend:
        return self._backend

    def start(self) -> bool:
        ok = bool(self._backend.start(self._local_name))
        self._running = ok
        if ok:
            set_active_server(self)
        return ok

    def stop(self) -> None:
        try:
            self._backend.stop()
        finally:
            self._running = False
            if get_active_server() is self:
                set_active_server(None)

    def push_otp(self, code: str, ttl_s: int | None = None) -> bool:
        if not self._running:
            return False
        payload = encode_otp_payload(code, ttl_s=ttl_s)
        self._ack_event.clear()
        self._last_ack = None
        return bool(self._backend.notify_otp(payload.encode("utf-8")))

    def push_payload(self, payload: str) -> bool:
        """Push a pre-encoded JSON payload (used by ``bluetooth_otp.ble_gatt_push``)."""
        if not self._running:
            return False
        self._ack_event.clear()
        self._last_ack = None
        return bool(self._backend.notify_otp(payload.encode("utf-8")))

    def wait_ack(self, timeout_s: float = 30.0) -> AckMessage | None:
        if self._ack_event.wait(timeout=max(0.0, float(timeout_s))):
            return self._last_ack
        return None

    def _on_ack(self, data: bytes) -> None:
        self._last_ack = parse_ack_payload(data)
        self._ack_event.set()


def get_active_server() -> BleGattServer | None:
    with _ACTIVE_LOCK:
        return _ACTIVE


def set_active_server(server: BleGattServer | None) -> None:
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = server


def main(argv: list[str] | None = None) -> int:
    """CLI: advertise DriveAuth OTP GATT until Ctrl-C; optional demo push."""
    import argparse

    ap = argparse.ArgumentParser(description="DriveAuth BLE GATT OTP peripheral")
    ap.add_argument("--name", default=LOCAL_NAME_DEFAULT)
    ap.add_argument(
        "--memory", action="store_true", help="Use in-memory backend (no BlueZ)"
    )
    ap.add_argument(
        "--demo-code", default="", help="If set, push this OTP once after start"
    )
    args = ap.parse_args(argv)

    if args.memory:
        server = BleGattServer(
            backend=MemoryBleGattBackend(), local_name=args.name, prefer_bluez=False
        )
    else:
        server = BleGattServer(local_name=args.name, prefer_bluez=True)
    if not server.start():
        logger.error("Failed to start BLE GATT server")
        return 1
    print(
        f"Advertising {args.name}\n"
        f"  service={BLE_GATT_SERVICE_UUID}\n"
        f"  otp_notify={BLE_GATT_OTP_CHAR_UUID}\n"
        f"  ack_write={BLE_GATT_ACK_CHAR_UUID}"
    )
    if args.demo_code:
        time.sleep(0.5)
        ok = server.push_otp(args.demo_code)
        print(f"demo push_otp({args.demo_code!r}) -> {ok}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
