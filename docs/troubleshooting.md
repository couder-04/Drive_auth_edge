# Troubleshooting

Grounded in the log lines and fail-closed paths the code actually emits.
Search logs for the quoted strings.

## Dashboard returns 401 / 503 on admin routes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Invalid or missing dashboard API key` | Missing/wrong `X-API-Key` or Bearer | Set `DRIVEAUTH_DASHBOARD_API_KEY` and send header; UI injects key when pages are served from the same process |
| `503 … API_KEY is not set` | No key and insecure mode off | Configure key in `secrets.env`, or `DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1` for localhost only |

## Matcher not ready / bootstrap

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `DriveAuth: voice matcher not ready` | No ECAPA / no enroll template | `python scripts/bootstrap.py` then enroll |
| `DriveAuth: face matcher not ready` | No MobileFaceNet / no face template | Same as above |
| `Stage-2 heads missing` | PAD/calibrator/risk/trust ONNX absent | Train scripts or copy a complete store; optional `DRIVEAUTH_REQUIRE_STAGE2=1` |
| Unexpected mock behaviour | Silent fallback removed | Use `DRIVEAUTH_USE_MOCK=1` or explicit `DRIVEAUTH_ALLOW_MOCK_FALLBACK=1` |

## Fingerprint sensor not detected

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `PyFingerprintAdapter: pyfingerprint not installed` | Missing extra | `pip install -e ".[finger]"` |
| `PyFingerprintAdapter: port /dev/ttyUSB0 not found` | No USB-serial node | Check cable/CH340; try `DRIVEAUTH_FINGER_UART=/dev/ttyAMA0` |
| `PyFingerprintAdapter: open failed on …` | Wrong port / baud / wiring | Confirm 57600 8N1; 3.3 V TTL (not RS-232) |
| `PyFingerprintAdapter: password verify failed` | Non-default sensor password | Pass `password=` into `PyFingerprintAdapter` |
| `PyFingerprintAdapter: readImage timed out` | No finger on platen | Place finger; raise `DRIVEAUTH_FINGER_CAPTURE_TIMEOUT_S` |
| `Finger sensor: no R307/AS608 UART detected — falling back to ManualFingerSensor` | Expected without HW | Set `DRIVEAUTH_FINGER_MANUAL=1` to silence, or attach sensor |
| `FingerDaemon: sensor open failed — refusing to listen` | `open()` returned False with no fallback | Check adapter; or allow manual fallback |
| Matcher never probes finger | Flag off | `DRIVEAUTH_FINGERPRINT_AVAILABLE=1` and real/non-mock finger matcher |

Daemon protocol: client sends `SCAN\n` on `DRIVEAUTH_FINGER_SOCKET` (default
`/tmp/driveauth_finger.sock`); expects exactly 65536 raw bytes.

## Bluetooth pairing / OTP fails

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `BT OTP: refusing delivery — registered/paired MAC mismatch` | Head-unit paired phone ≠ enrolled MAC | Write correct MAC to `store/contacts/<driver_id>.bt_mac` |
| `BT OTP: MAP and BLE GATT both unavailable` | No MAP agent and no GATT server | Start `driveauth-ble-gatt` / companion PWA; configure BlueZ MAP |
| `BT OTP: BlueZ OBEX present but MAP agent not configured` | OBEX without messaging agent | Pair with MAP access, or rely on BLE GATT fallback |
| `BLE GATT: BlueZ deps missing` | No `dbus-python` / BlueZ | `pip install -e ".[bluetooth]"` + `apt install bluez` |
| `BLE GATT: BlueZ start failed` | Permissions / adapter down | `bluetoothctl power on`; run with access to system bus |
| Ladder rejects with `otp_unavailable` | Delivery returned False | Fix MAC match + MAP/BLE; see tests in `tests/test_phase1_ladder_otp.py` |

Payment OTP (`otp_mobile` HTTP) is a **different** path from identity-ladder
Bluetooth OTP — do not share `OTPStepUp` instances across the two.

## Hailo device not found

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `HailoFaceMatcher: hailo_platform not installed` | Vendor SDK absent | Install HailoRT / `hailo_platform` on the device (not on PyPI via this repo) |
| `HailoFaceMatcher: HEF not found at …` | Missing `.hef` | Set `DRIVEAUTH_HAILO_HEF` / place file; convert models on real hardware |
| `HailoFaceMatcher: device open failed` | No PCIe/M.2 device | Check `lspci` / Hailo device node |
| `DriveAuth: Hailo backend requested but not ready — ONNX/mock face` | Fail-soft fallback | Expected when `DRIVEAUTH_FACE_BACKEND=hailo` without a live device |

Code-only work cannot produce real Hailo latency numbers — benchmark on device.

## Camera / mic

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `OpenCVFrameBackend: opencv not installed` | Missing face extra | `pip install -e ".[face]"` |
| `…: camera N open failed` | Wrong index / permissions | Try `DRIVEAUTH_IR_CAMERA_INDEX=0`; add user to `video` group |
| `MicArrayCapture: read failed` | Backend/device drop | Reconnect USB; check PortAudio |
| Face `available=False` after disconnect | Fail-closed probe | Reconnect camera; next `authenticate()` recovers (see `tests/test_phase6_failure_recovery.py`) |

## Tests failing on a fresh clone

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,onnx,dashboard]"
pytest -q
```

Common issues:

1. **Wrong Python** — need 3.11+ (`requires-python = ">=3.11"`).
2. **Editable install missing** — `ModuleNotFoundError: driveauth` → `pip install -e ".[dev]"`.
3. **Optional model files** — some Phase 5/6 tests `pytest.skip` when
   `driveauth_store_phase2a/*.onnx` is absent; that is expected.
4. **HW-gated tests** — `DRIVEAUTH_BT_HW_TEST=1` / `DRIVEAUTH_HAILO_HW_TEST=1`
   are skipped unless you set the env on real hardware.
5. **Perf CSV permission** — if home is read-only, set
   `DRIVEAUTH_PERF_LOG=/tmp/driveauth_perf.csv`.

Fast mockable subset (same as `scripts/install.sh`):

```bash
pytest -q tests/test_core.py tests/test_phase5_failure_modes.py \
  tests/test_perf_telemetry.py tests/test_finger_uart.py \
  tests/test_integration_e2e.py tests/test_phase6_failure_recovery.py
```

## GPIO / CAN

| Symptom / log | Cause | Fix |
|---------------|-------|-----|
| `GPIORelay: RPi.GPIO not installed` | Not on Pi / missing extra | `pip install -e ".[gpio]"` on Raspberry Pi OS |
| `CanLogger: bus open failed` | No interface / missing `python-can` | Enable CAN overlay; `pip install -e ".[can]"` |

## Integrity / secrets

When `DRIVEAUTH_INTEGRITY_CHECK=1`, store manifest mismatches fail closed at
`DriveAuth.load` — see `docs/security-assumptions.md` and `docs/key-provisioning.md`.
Never commit `secrets.env` or `.bio_key` material.
