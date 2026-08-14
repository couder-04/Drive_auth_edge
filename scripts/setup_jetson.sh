#!/usr/bin/env bash
# DriveAuth Edge — Jetson Orin Nano first-boot setup (JetPack 6.x).
# Installs system packages + Python venv. Does NOT wire physical sensors.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

echo "==> Detect board"
if [[ -f /etc/nv_tegra_release ]]; then
  cat /etc/nv_tegra_release || true
else
  echo "warning: /etc/nv_tegra_release missing — continuing anyway"
fi

echo "==> System packages (OpenCV/soundfile/ffmpeg/serial/USB)"
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends \
  python3 \
  python3-venv \
  python3-dev \
  python3-pip \
  build-essential \
  cmake \
  pkg-config \
  git \
  libsndfile1 \
  ffmpeg \
  libgl1 \
  libglib2.0-0 \
  portaudio19-dev \
  libusb-1.0-0-dev \
  libxmu-dev \
  libxi-dev \
  freeglut3-dev \
  bluez \
  can-utils || true

# Optional: libfreenect from apt when packaged; otherwise build from source below.
$SUDO apt-get install -y --no-install-recommends libfreenect-dev libfreenect0.5 || true

echo "==> Python package (Jetson extras — no RPi.GPIO)"
export DRIVEAUTH_VENV="${DRIVEAUTH_VENV:-$ROOT/.venv}"
PYTHON="${PYTHON:-python3}"
if [[ ! -d "$DRIVEAUTH_VENV" ]]; then
  "$PYTHON" -m venv "$DRIVEAUTH_VENV"
fi
# shellcheck disable=SC1091
source "$DRIVEAUTH_VENV/bin/activate"
python -m pip install --upgrade pip wheel
pip install -e ".[dev,jetson]"

echo "==> Optional libfreenect Python bindings"
if python -c "import freenect" 2>/dev/null; then
  echo "freenect already importable"
elif [[ -d /usr/include/libfreenect ]]; then
  echo "note: libfreenect headers present — build wrappers if import still fails:"
  echo "  git clone https://github.com/OpenKinect/libfreenect.git /tmp/libfreenect"
  echo "  cd /tmp/libfreenect/wrappers/python && python setup.py install"
else
  echo "note: install libfreenect for Kinect RGB+depth:"
  echo "  https://github.com/OpenKinect/libfreenect"
fi

echo "==> USB autosuspend (Kinect on Jetson often needs this)"
for f in /sys/bus/usb/devices/*/power/autosuspend; do
  echo -1 | $SUDO tee "$f" >/dev/null 2>&1 || true
done

echo "==> Bootstrap models (store)"
STORE="${DRIVEAUTH_STORE_DIR:-$ROOT/driveauth_store}"
python scripts/bootstrap.py --store "$STORE" || true

echo ""
echo "============================================================"
echo " Jetson Orin software setup complete. Wire + probe:"
echo "============================================================"
cat <<'EOF'
  [ ] GT-511C3 UART     — 3.3V TTL TX/RX crossed, GND common
                          export DRIVEAUTH_FINGER_SENSOR=gt511
                          export DRIVEAUTH_FINGER_UART=/dev/ttyUSB0   # or ttyTHS*
                          driveauth-finger-daemon
                          export DRIVEAUTH_FINGERPRINT_AVAILABLE=1
  [ ] Xbox 360 Kinect   — powered USB hub recommended; libfreenect
                          export DRIVEAUTH_CAMERA_BACKEND=kinect
                          export DRIVEAUTH_IR_LIVENESS_ENABLED=1
                          export DRIVEAUTH_IR_LIVENESS_ENSEMBLE=1
  [ ] Kinect mic array  — export DRIVEAUTH_MIC_DEVICE=Kinect   # substring
  [ ] Probe             — driveauth-probe-hw
  [ ] Enroll finger     — POST /api/register/finger (dashboard)
  [ ] Recapture face    — scripts/recapture_driver1_genuine.py

Suggested env block (save as phases/jetson_orin.env):
  DRIVEAUTH_STORE_DIR=./driveauth_store
  DRIVEAUTH_FINGER_SENSOR=gt511
  DRIVEAUTH_FINGER_UART=/dev/ttyUSB0
  DRIVEAUTH_FINGERPRINT_AVAILABLE=1
  DRIVEAUTH_CAMERA_BACKEND=kinect
  DRIVEAUTH_IR_LIVENESS_ENABLED=1
  DRIVEAUTH_IR_LIVENESS_ENSEMBLE=1
  DRIVEAUTH_MIC_DEVICE=Kinect

Docs: docs/install-guide.md · docs/troubleshooting.md · docs/configuration.md
EOF
