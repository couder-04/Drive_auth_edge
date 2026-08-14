"""Hardware adapters for DriveAuth Edge (Pi + Hailo + sensors).

Policy / matchers stay in ``driveauth``; this package only speaks sensor,
daemon, Bluetooth, capture, liveness, Hailo, actuation, and telematics
contracts. Optional extras keep the core install free of UART / BlueZ /
GPIO / HailoRT dependencies.
"""

from __future__ import annotations

from hardware.actuation import (
    ActuationListener,
    ActuationWatchdog,
    FlakyAckRelay,
    GPIORelay,
    LogSpeaker,
    NullRelay,
    NullSpeaker,
)
from hardware.bluetooth_otp import (
    BLE_GATT_ACK_CHAR_UUID,
    BLE_GATT_CHAR_UUID,
    BLE_GATT_OTP_CHAR_UUID,
    BLE_GATT_SERVICE_UUID,
    BluetoothOTPDelivery,
)
from hardware.ble_gatt_server import BleGattServer, MemoryBleGattBackend
from hardware.can_logger import CanLogger, TXN_CSV_COLUMNS
from hardware.finger_daemon import FingerDaemon
from hardware.finger_uart import (
    AS608Adapter,
    FingerSensorAdapter,
    ManualFingerSensor,
    PyFingerprintAdapter,
    R307Adapter,
    open_default_sensor,
    probe_pyfingerprint,
)
from hardware.gt511c3 import GT511C3Adapter, probe_gt511, resize_gt511_to_scan
from hardware.fleet_telemetry import FleetTelemetryReporter, build_telemetry_payload
from hardware.hailo_face import HailoFaceMatcher
from hardware.ir_capture import IRCameraCapture, MicArrayCapture, RGBCameraCapture
from hardware.ir_liveness import (
    IRLivenessChecker,
    LivenessResult,
    combine_liveness_scores,
    score_blink_motion,
    score_depth,
    score_moire,
)
from hardware.kinect_capture import (
    FreenectDepthBackend,
    FreenectRGBBackend,
    KinectCapture,
    SoundDeviceAudioBackend,
    open_ir_capture,
    open_mic_capture,
)
from hardware.ladder_otp import LadderOTPLane
from hardware.ota_client import OTAClient
from hardware.telematics import TelematicsIngest, sanitize_vehicle_fields

__all__ = [
    "ActuationListener",
    "ActuationWatchdog",
    "BLE_GATT_ACK_CHAR_UUID",
    "BLE_GATT_CHAR_UUID",
    "BLE_GATT_OTP_CHAR_UUID",
    "BLE_GATT_SERVICE_UUID",
    "BleGattServer",
    "BluetoothOTPDelivery",
    "CanLogger",
    "FingerDaemon",
    "FingerSensorAdapter",
    "FlakyAckRelay",
    "FleetTelemetryReporter",
    "FreenectDepthBackend",
    "FreenectRGBBackend",
    "GPIORelay",
    "GT511C3Adapter",
    "HailoFaceMatcher",
    "IRCameraCapture",
    "IRLivenessChecker",
    "KinectCapture",
    "LadderOTPLane",
    "LivenessResult",
    "LogSpeaker",
    "AS608Adapter",
    "ManualFingerSensor",
    "MemoryBleGattBackend",
    "MicArrayCapture",
    "NullRelay",
    "NullSpeaker",
    "OTAClient",
    "PyFingerprintAdapter",
    "R307Adapter",
    "RGBCameraCapture",
    "SoundDeviceAudioBackend",
    "TXN_CSV_COLUMNS",
    "TelematicsIngest",
    "build_telemetry_payload",
    "combine_liveness_scores",
    "open_default_sensor",
    "open_ir_capture",
    "open_mic_capture",
    "probe_gt511",
    "probe_pyfingerprint",
    "resize_gt511_to_scan",
    "sanitize_vehicle_fields",
    "score_blink_motion",
    "score_depth",
    "score_moire",
]
