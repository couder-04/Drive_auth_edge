#!/usr/bin/env bash
# Phase 1b bootstrap on NVIDIA Thor (mock pipeline).
# Run from repo root on Thor:
#   bash scripts/phase1b_thor_bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then PY=python3.11
  elif command -v python3 >/dev/null 2>&1; then PY=python3
  else
    echo "Need python3.11 or python3 on PATH" >&2
    exit 1
  fi
fi

echo "== Python: $($PY --version) =="
echo "== Device: $(uname -a) =="

if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -U pip wheel
pip install -e ".[dev,dashboard,onnx]"

export DRIVEAUTH_USE_MOCK=1
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0
export DRIVEAUTH_DASHBOARD_HOST=0.0.0.0
export DRIVEAUTH_DASHBOARD_PORT=8765

STORE="${DRIVEAUTH_STORE_DIR:-$HOME/driveauth_store}"
mkdir -p "$STORE"
export DRIVEAUTH_STORE_DIR="$STORE"
echo "== STORE: $DRIVEAUTH_STORE_DIR =="

echo "== import driveauth =="
python -c "import driveauth; print('driveauth OK', driveauth.__file__)"

echo "== ORT providers =="
python - <<'PY' || true
try:
    import onnxruntime as ort
    print("ORT", ort.__version__)
    print("providers", ort.get_available_providers())
except Exception as e:
    print("ORT skip:", e)
PY

echo "== pytest =="
pytest -q

echo "== driveauth-demo =="
driveauth-demo

echo "== latency bench → phases/thor.txt =="
python scripts/phase1b_thor_bench.py --out phases/thor.txt

echo
echo "Phase 1b core checks done."
echo "Start dashboard:  driveauth-dashboard"
echo "From Mac browser: http://<thor-tunnel-or-ip>:8765"
echo "Copy phases/thor.txt back to the Mac repo if this clone is ephemeral."
