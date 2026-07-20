"""Hardware adapters for DriveAuth Edge (Pi + Hailo + sensors).

Policy / matchers stay in ``driveauth``; this package only speaks sensor,
daemon, Bluetooth, capture, liveness, Hailo, actuation, and telematics
contracts. Optional extras keep the core install free of UART / BlueZ /
GPIO / HailoRT dependencies.
"""

from __future__ import annotations

from hardware.actuation import ActuationListener, GPIORelay, LogSpeaker, NullRelay, NullSpeaker
from hardware.bluetooth_otp import (
    BLE_GATT_CHAR_UUID,
    BLE_GATT_SERVICE_UUID,
    BluetoothOTPDelivery,
)
from hardware.can_logger import CanLogger, TXN_CSV_COLUMNS
from hardware.finger_daemon import FingerDaemon
from hardware.finger_uart import FingerSensorAdapter, ManualFingerSensor, PyFingerprintAdapter
from hardware.hailo_face import HailoFaceMatcher
from hardware.ir_capture import IRCameraCapture, MicArrayCapture, RGBCameraCapture
from hardware.ir_liveness import IRLivenessChecker, LivenessResult
from hardware.ladder_otp import LadderOTPLane
from hardware.telematics import TelematicsIngest, sanitize_vehicle_fields

__all__ = [
    "ActuationListener",
    "BLE_GATT_CHAR_UUID",
    "BLE_GATT_SERVICE_UUID",
    "BluetoothOTPDelivery",
    "CanLogger",
    "FingerDaemon",
    "FingerSensorAdapter",
    "GPIORelay",
    "HailoFaceMatcher",
    "IRCameraCapture",
    "IRLivenessChecker",
    "LadderOTPLane",
    "LivenessResult",
    "LogSpeaker",
    "ManualFingerSensor",
    "MicArrayCapture",
    "NullRelay",
    "NullSpeaker",
    "PyFingerprintAdapter",
    "RGBCameraCapture",
    "TXN_CSV_COLUMNS",
    "TelematicsIngest",
    "sanitize_vehicle_fields",
]
