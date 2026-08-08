# Bluetooth MAP OTP setup (TODO 9)

DriveAuth tries **MAP first**, then **BLE GATT** (`hardware/bluetooth_otp.py`).
MAP push is head-unit specific; the repo ships a presence-check stub until an
OBEX MAP agent is configured on the paired phone/head unit.

## Prerequisites

- Linux head unit or Pi with BlueZ ≥ 5.6
- Paired phone with MAP profile enabled
- `pip install -e ".[bluetooth]"` (PyGObject + dbus)

## Environment

```bash
DRIVEAUTH_DRIVER_BT_MAC=AA:BB:CC:DD:EE:FF   # phone MAC (store/contacts/<id>.bt_mac)
DRIVEAUTH_BLE_GATT_ENABLED=1                  # car-side GATT fallback server
```

## Head-unit checklist

1. Pair phone over Bluetooth (HFP + MAP).
2. Confirm OBEX: `dbus-send --session --print-reply \
   --dest=org.freedesktop.DBus /org/freedesktop/DBus \
   org.freedesktop.DBus.ListNames | grep obex`
3. Grant MAP SMS/message access on the phone when prompted.
4. Run ladder OTP test: `DRIVEAUTH_BT_HW_TEST=1 pytest tests/test_phase1_ladder_otp.py -k real_hardware`

## Dev mock (no head unit)

```bash
python scripts/mock_map_agent.py &
pytest tests/test_phase1_ladder_otp.py -k map
```

## Known limitation

`_bluez_map_send()` returns `False` when no MAP agent accepts the push — this
is intentional fail-closed behaviour; BLE GATT carries the OTP instead.
