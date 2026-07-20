#!/usr/bin/env bash
# DriveAuth Edge — Raspberry Pi 5 first-boot setup.
# Installs system packages + Python venv. Does NOT wire physical sensors.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "==> System packages (OpenCV/soundfile/ffmpeg runtime)"
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends \
  python3 \
  python3-venv \
  python3-dev \
  build-essential \
  libsndfile1 \
  ffmpeg \
  libgl1 \
  libglib2.0-0 \
  libatlas-base-dev \
  portaudio19-dev \
  git

# Optional BlueZ / CAN tools when present in apt.
$SUDO apt-get install -y --no-install-recommends bluez can-utils || true

echo "==> Python package (hardware extras)"
export DRIVEAUTH_VENV="${DRIVEAUTH_VENV:-$ROOT/.venv}"
bash "$ROOT/scripts/install.sh" --with-hardware

echo ""
echo "============================================================"
echo " Pi 5 software setup complete. Physical wiring still needed:"
echo "============================================================"
cat <<'EOF'
  [ ] Camera (IR/RGB)     — CSI/USB; set DRIVEAUTH_IR_CAMERA_INDEX / RGB_CAMERA_INDEX
  [ ] Mic array           — USB/I2S; exercise via hardware.ir_capture.MicArrayCapture
  [ ] Fingerprint UART    — R307/AS608 on /dev/ttyUSB0 (or DRIVEAUTH_FINGER_UART)
                            then: driveauth-finger-daemon
                            set DRIVEAUTH_FINGERPRINT_AVAILABLE=1
  [ ] CAN HAT             — enable overlay, then: driveauth-can-logger
  [ ] Bluetooth head-unit — pair phone MAC → store/contacts/<driver>.bt_mac
                            companion OTP: driveauth-ble-gatt
  [ ] Hailo (optional)    — install vendor SDK + .hef; DRIVEAUTH_FACE_BACKEND=hailo
  [ ] GPIO actuation      — BCM pin for relay (hardware.actuation.GPIORelay)

Extras map (pyproject.toml):
  finger → pyfingerprint          bluetooth → dbus-python
  gpio   → RPi.GPIO               can       → python-can
  face   → opencv + onnxruntime   hailo     → (empty; vendor SDK)
  hardware = finger+bluetooth+gpio+face+can

Docs: docs/install-guide.md · docs/troubleshooting.md
EOF
