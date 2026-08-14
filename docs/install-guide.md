# Install guide (Pi 5 + local)

Software-only setup for DriveAuth Edge. Physical camera / mic / fingerprint /
CAN / Bluetooth wiring is listed at the end — scripts cannot do that part.

## Prerequisites

- Python **3.11+**
- On Raspberry Pi 5: Raspberry Pi OS (Bookworm) with network access for `apt`/`pip`

## Quick start (laptop / CI)

```bash
git clone <this-repo> && cd staged_driveauth-edge
make install                 # or: bash scripts/install.sh
source .venv/bin/activate
cp secrets.env.example secrets.env
# Required for mutating dashboard routes:
#   DRIVEAUTH_DASHBOARD_API_KEY=<secret>
# Localhost demos without a key (never on a public bind):
#   DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1
make bootstrap               # Stage-1 download + Stage-2 checklist
make test
DRIVEAUTH_USE_MOCK=1 DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1 driveauth-dashboard
# http://127.0.0.1:8765
```

### Model bootstrap (no silent fallback)

```bash
python scripts/bootstrap.py --store ./driveauth_store_phase2a
python scripts/bootstrap.py --check-only
```

- Real matchers require Stage-1 ECAPA + MobileFaceNet (and enrollment).
- Missing voice/face raises unless `DRIVEAUTH_USE_MOCK=1` or explicit
  `DRIVEAUTH_ALLOW_MOCK_FALLBACK=1`.
- Stage-2 heads (`risk_gbt.onnx`, `trust_fusion.onnx`, PAD/calibrators) are
  reported clearly; set `DRIVEAUTH_REQUIRE_STAGE2=1` to fail closed when absent.

Flags for `scripts/install.sh`:

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
| `finger` | pyfingerprint + pyserial | R307/AS608 **or** GT-511C3 UART |
| `kinect` | sounddevice + face | Kinect mic + OpenCV; freenect is system-installed |
| `jetson` | finger+bluetooth+face+can+voice+onnx+dashboard+kinect | Orin edge bundle (no RPi.GPIO) |
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
# Auto-detect GT-511C3 (9600) then R307/AS608 (57600) on DRIVEAUTH_FINGER_UART
# (default /dev/ttyUSB0); falls back to ManualFingerSensor when no UART answers.
driveauth-finger-daemon

# Force GT-511C3 (Jetson Orin + SparkFun/ADH module)
DRIVEAUTH_FINGER_SENSOR=gt511 DRIVEAUTH_FINGER_UART=/dev/ttyUSB0 driveauth-finger-daemon

# Force R307/AS608
DRIVEAUTH_FINGER_SENSOR=r307 driveauth-finger-daemon

# Force manual / CI stand-in
DRIVEAUTH_FINGER_MANUAL=1 driveauth-finger-daemon

# Fail hard instead of manual fallback
DRIVEAUTH_FINGER_NO_FALLBACK=1 driveauth-finger-daemon
```

Set `DRIVEAUTH_FINGERPRINT_AVAILABLE=1` so the decision ladder probes finger.

## Jetson Orin Nano

```bash
bash scripts/setup_jetson.sh
set -a && source phases/jetson_orin.env && set +a
driveauth-probe-hw
driveauth-finger-daemon &
driveauth-dashboard
```

Kinect (Xbox 360 / v1) needs system `libfreenect` + Python `freenect` bindings;
`DRIVEAUTH_CAMERA_BACKEND=kinect` enables RGB+depth for IR liveness ensemble.

## Perf telemetry

Always-on local CSV (separate from the security audit log):

```bash
export DRIVEAUTH_PERF_LOG=~/.driveauth/perf/perf.csv   # default
# DRIVEAUTH_PERF_TELEMETRY=0   # disable
```

Fleet UI: `/fleet` → latency + CPU/RAM panel (`GET /api/fleet/perf`).

## Physical checklist (script cannot do this)

Same list printed by `setup_pi.sh` / `setup_jetson.sh`:

1. IR/RGB camera — CSI/USB/Kinect; `DRIVEAUTH_IR_CAMERA_INDEX` / `DRIVEAUTH_CAMERA_BACKEND`
2. Mic array — USB/I2S/Kinect; `DRIVEAUTH_MIC_DEVICE`
3. Fingerprint UART — **GT-511C3** (`DRIVEAUTH_FINGER_SENSOR=gt511`) or R307/AS608 on `/dev/ttyUSB0`
4. CAN HAT — enable overlay; `driveauth-can-logger`
5. Bluetooth head-unit — pair phone; write `store/contacts/<driver>.bt_mac`
6. Optional Hailo — vendor SDK + `.hef`; `DRIVEAUTH_FACE_BACKEND=hailo`
7. GPIO relay — BCM pin for `GPIORelay` (Pi; not Jetson)

See also: [troubleshooting.md](troubleshooting.md), [api-reference.md](api-reference.md),
[configuration.md](configuration.md).
