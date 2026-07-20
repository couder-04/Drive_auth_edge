"""Hardware adapters for DriveAuth Edge (Pi + Hailo + sensors).

Policy / matchers stay in ``driveauth``; this package only speaks sensor,
daemon, Bluetooth, and actuation contracts. Optional extras keep the core
install free of UART / BlueZ / GPIO dependencies.
"""

from __future__ import annotations

from hardware.bluetooth_otp import (
    BLE_GATT_CHAR_UUID,
    BLE_GATT_SERVICE_UUID,
    BluetoothOTPDelivery,
)
from hardware.finger_daemon import FingerDaemon
from hardware.finger_uart import FingerSensorAdapter, ManualFingerSensor, PyFingerprintAdapter
from hardware.ladder_otp import LadderOTPLane

__all__ = [
    "BLE_GATT_CHAR_UUID",
    "BLE_GATT_SERVICE_UUID",
    "BluetoothOTPDelivery",
    "FingerDaemon",
    "FingerSensorAdapter",
    "LadderOTPLane",
    "ManualFingerSensor",
    "PyFingerprintAdapter",
]
