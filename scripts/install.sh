#!/usr/bin/env bash
# DriveAuth Edge — one-command local install + sanity check.
# Usage: bash scripts/install.sh [--with-hardware] [--skip-tests]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_HARDWARE=0
SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --with-hardware) WITH_HARDWARE=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    -h|--help)
      echo "Usage: bash scripts/install.sh [--with-hardware] [--skip-tests]"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found" >&2
  exit 1
fi

PY_VER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
# Require 3.11+
"$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "error: Python 3.11+ required (found $PY_VER)" >&2
  exit 1
}

VENV="${DRIVEAUTH_VENV:-$ROOT/.venv}"
if [[ ! -d "$VENV" ]]; then
  echo "==> Creating venv at $VENV"
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel

EXTRAS="dev,onnx,dashboard"
if [[ "$WITH_HARDWARE" -eq 1 ]]; then
  EXTRAS="${EXTRAS},hardware"
  echo "==> Installing with hardware extras (finger/bluetooth/gpio/face/can)"
else
  # Best-effort detect: UART node or RPi model → suggest hardware later.
  if [[ -e /dev/ttyUSB0 || -e /proc/device-tree/model ]] && grep -qi "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "note: Raspberry Pi detected — re-run with --with-hardware or use scripts/setup_pi.sh"
  fi
fi

echo "==> pip install -e \".[${EXTRAS}]\""
pip install -e ".[${EXTRAS}]"

echo "==> Sanity: imports"
python - <<'PY'
import driveauth
from driveauth import DriveAuth, Decision, DriveAuthResult
from driveauth.perf_telemetry import PerfTelemetry, CSV_COLUMNS
from hardware.finger_uart import open_default_sensor, PyFingerprintAdapter
print("driveauth", driveauth.__version__)
print("csv_columns", len(CSV_COLUMNS))
print("ok")
PY

if [[ "$SKIP_TESTS" -eq 1 ]]; then
  echo "==> Skipping pytest (--skip-tests)"
  exit 0
fi

echo "==> Sanity: pytest (mockable subset)"
# Keep the first-run check fast and free of optional HW / real models.
pytest -q \
  tests/test_core.py \
  tests/test_phase5_failure_modes.py \
  tests/test_perf_telemetry.py \
  tests/test_finger_uart.py \
  tests/test_integration_e2e.py \
  tests/test_phase6_failure_recovery.py \
  -q --tb=line

echo ""
echo "Install complete."
echo "  activate:  source $VENV/bin/activate"
echo "  dashboard: driveauth-dashboard"
echo "  Pi first-boot: bash scripts/setup_pi.sh"
