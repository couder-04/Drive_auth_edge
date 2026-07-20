# Install guide (Pi 5 + local)

Software-only setup for DriveAuth Edge. Physical camera / mic / fingerprint /
CAN / Bluetooth wiring is listed at the end — scripts cannot do that part.

## Prerequisites

- Python **3.11+**
- On Raspberry Pi 5: Raspberry Pi OS (Bookworm) with network access for `apt`/`pip`

## Quick start (laptop / CI)

```bash
git clone <this-repo> && cd Drive_auth_edge   # or staged_driveauth-edge
bash scripts/install.sh
source .venv/bin/activate
driveauth-dashboard   # http://127.0.0.1:8765
```

Flags:

| Flag | Effect |
|------|--------|
| `--with-hardware` | Also install `.[hardware]` (finger, bluetooth, gpio, face, can) |
| `--skip-tests` | Skip the first-run pytest sanity check |

The script creates `.venv`, installs `.[dev,onnx,dashboard]` (plus hardware when
requested), verifies imports, and runs a mockable pytest subset.

## Raspberry Pi 5 first boot

```bash
bash scripts/setup_pi.sh
```

This installs system packages aligned with the Docker images
(`libsndfile1`, `ffmpeg`, `libgl1`, `libglib2.0-0`, build tools, BlueZ/can-utils
when available), then runs `install.sh --with-hardware`.

## `pyproject.toml` extras map

| Extra | Pulls in | Needed for |
|-------|----------|------------|
| *(core)* | numpy, cryptography, PyYAML | `DriveAuth` API, policy, fusion |
| `dev` | pytest, ruff, psutil | tests + perf telemetry |
| `onnx` | onnxruntime | risk / fusion / finger ONNX heads |
| `voice` | torch, speechbrain | ECAPA-TDNN voice matcher |
| `face` | opencv-python, onnxruntime | MobileFaceNet + OpenCV capture |
| `dashboard` | fastapi, uvicorn, multipart, psutil | web UI + `/api/fleet/perf` |
| `orchestrator` | onnxruntime | PolicyMLP dynamic weights |
| `train` | lightgbm, sklearn, onnx export | training scripts only |
| `finger` | pyfingerprint | R307/AS608 UART (`PyFingerprintAdapter`) |
| `bluetooth` | dbus-python | BlueZ MAP / BLE GATT OTP |
| `gpio` | RPi.GPIO | actuation relay |
| `can` | python-can | CAN logger |
| `tpm` | tpm2-pytss | optional key protection |
| `hailo` | *(empty)* | declare grouping; install vendor Hailo SDK separately |
| `perf` | psutil | CPU/RAM snapshots (also in `dev`/`dashboard`) |
| `hardware` | finger + bluetooth + gpio + face + can | Pi edge bundle |
| `standalone` | voice + face + onnx + dashboard | product demo path |
| `all` | everything above | full local workstation |

Examples:

```bash
pip install -e ".[dev]"                         # tests only
pip install -e ".[voice,face,onnx,dashboard]"   # real voice/face + UI
pip install -e ".[hardware]"                    # Pi sensors
pip install -e ".[finger]"                      # UART fingerprint only
```

## Docker (full pipeline)

Dashboard-only cloud image: `Dockerfile`.

Edge pipeline image (copies `hardware/`, mock-friendly defaults):

```bash
docker compose up --build
# dashboard → http://localhost:8765
# finger-daemon uses ManualFingerSensor (no host UART in compose)
```

Or:

```bash
docker build -f Dockerfile.edge -t driveauth-edge:pipeline .
```

`orchestrator.py` PolicyMLP runs **in-process** inside `DriveAuth` — compose
only splits dashboard vs finger daemon (Unix socket), matching real topology.

## Fingerprint daemon

```bash
# Auto-detect R307/AS608 on DRIVEAUTH_FINGER_UART (default /dev/ttyUSB0);
# falls back to ManualFingerSensor when no UART answers.
driveauth-finger-daemon

# Force manual / CI stand-in
DRIVEAUTH_FINGER_MANUAL=1 driveauth-finger-daemon

# Fail hard instead of manual fallback
DRIVEAUTH_FINGER_NO_FALLBACK=1 driveauth-finger-daemon
```

Set `DRIVEAUTH_FINGERPRINT_AVAILABLE=1` so the decision ladder probes finger.

## Perf telemetry

Always-on local CSV (separate from the security audit log):

```bash
export DRIVEAUTH_PERF_LOG=~/.driveauth/perf/perf.csv   # default
# DRIVEAUTH_PERF_TELEMETRY=0   # disable
```

Fleet UI: `/fleet` → latency + CPU/RAM panel (`GET /api/fleet/perf`).

## Physical checklist (script cannot do this)

Same list printed by `setup_pi.sh`:

1. IR/RGB camera — CSI/USB; `DRIVEAUTH_IR_CAMERA_INDEX` / `DRIVEAUTH_RGB_CAMERA_INDEX`
2. Mic array — USB/I2S
3. Fingerprint UART — R307/AS608 on `/dev/ttyUSB0` (or `DRIVEAUTH_FINGER_UART`)
4. CAN HAT — enable overlay; `driveauth-can-logger`
5. Bluetooth head-unit — pair phone; write `store/contacts/<driver>.bt_mac`
6. Optional Hailo — vendor SDK + `.hef`; `DRIVEAUTH_FACE_BACKEND=hailo`
7. GPIO relay — BCM pin for `GPIORelay`

See also: [troubleshooting.md](troubleshooting.md), [api-reference.md](api-reference.md),
[configuration.md](configuration.md).
