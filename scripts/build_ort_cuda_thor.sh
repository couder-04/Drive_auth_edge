#!/usr/bin/env bash
# Build onnxruntime-gpu for NVIDIA Thor (compute capability 11.0 / SM110).
#
# Run ON Thor inside the project venv:
#   source .venv/bin/activate
#   bash scripts/build_ort_cuda_thor.sh
#
# Then unset CPU force and re-bench:
#   unset DRIVEAUTH_ORT_PROVIDERS
#   python scripts/phase2a_bench.py --store "$DRIVEAUTH_STORE_DIR" \
#     --out phases/phase2a-thor.txt --device cuda --n 30
#
# Wall time: often 1–3 hours. Needs ~32+ GB free RAM (lower --parallel if OOM).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ROOT="${ORT_BUILD_ROOT:-$HOME/ort-build-thor}"
ORT_BRANCH="${ORT_BRANCH:-v1.23.1}"
PARALLEL="${ORT_PARALLEL:-6}"
PYTHON="${PYTHON:-python}"

echo "== DriveAuth: build ORT CUDA for Thor SM110 =="
echo "BUILD_ROOT=$BUILD_ROOT  BRANCH=$ORT_BRANCH  PARALLEL=$PARALLEL"

# --- sanity ---
if ! command -v nvidia-smi >/dev/null; then
  echo "FAIL: nvidia-smi not found" >&2
  exit 1
fi
CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')"
echo "GPU compute_cap=$CAP"
if [[ "$CAP" != "11.0" ]]; then
  echo "WARN: this script targets SM110 (11.0). Got $CAP — adjust CMAKE_CUDA_ARCHITECTURES if needed."
fi

"$PYTHON" - <<'PY'
import sys
print("Python", sys.version)
PY

CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
CUDNN_HOME="${CUDNN_HOME:-/usr/lib/aarch64-linux-gnu}"
if [[ ! -d "$CUDA_HOME" ]]; then
  echo "FAIL: CUDA_HOME=$CUDA_HOME missing" >&2
  exit 1
fi
echo "CUDA_HOME=$CUDA_HOME  CUDNN_HOME=$CUDNN_HOME"

# --- host deps (best-effort; may need sudo) ---
need_pkg() { dpkg -s "$1" >/dev/null 2>&1 || return 0; return 1; }
MISSING=()
for p in git cmake ninja-build g++ python3-dev patchelf; do
  if ! dpkg -s "$p" >/dev/null 2>&1; then MISSING+=("$p"); fi
done
if ((${#MISSING[@]})); then
  echo "Missing packages: ${MISSING[*]}"
  echo "Install with:  sudo apt-get update && sudo apt-get install -y ${MISSING[*]}"
  if command -v sudo >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
  else
    echo "FAIL: install packages then re-run" >&2
    exit 1
  fi
fi

pip install -U pip wheel setuptools numpy packaging "setuptools<81"

# --- source ---
mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"
if [[ ! -d onnxruntime/.git ]]; then
  git clone --recursive https://github.com/microsoft/onnxruntime.git
fi
cd onnxruntime
git fetch --tags --force
git checkout "$ORT_BRANCH"
git submodule sync --recursive
git submodule update --init --recursive

# Thor / sbsa CUDA 13 headers
export CXXFLAGS="${CXXFLAGS:--Wno-error=deprecated-declarations}"
export CPLUS_INCLUDE_PATH="/usr/local/cuda/targets/sbsa-linux/include/cccl:${CPLUS_INCLUDE_PATH:-}"

# Prefer 110-real;110-virtual (Thor). NVIDIA forum also accepts CMAKE_CUDA_ARCHITECTURES=110.
ARCH_LIST="${ORT_CUDA_ARCH:-110-real;110-virtual}"

echo "== building (this takes a long time) =="
# TensorRT optional: set ORT_USE_TENSORRT=1 to enable
EXTRA_TRT=()
if [[ "${ORT_USE_TENSORRT:-0}" == "1" ]]; then
  EXTRA_TRT+=(--use_tensorrt --tensorrt_home "$CUDNN_HOME")
fi

./build.sh \
  --config Release \
  --update \
  --build \
  --parallel "$PARALLEL" \
  --cmake_generator Ninja \
  --skip_tests \
  --enable_pybind \
  --build_wheel \
  --use_cuda \
  --cuda_home "$CUDA_HOME" \
  --cudnn_home "$CUDNN_HOME" \
  "${EXTRA_TRT[@]}" \
  --cmake_extra_defines "CMAKE_CUDA_ARCHITECTURES=${ARCH_LIST}" \
  --cmake_extra_defines "CMAKE_CUDA_FLAGS=--forward-unknown-to-host-compiler -Xcompiler=-Wno-strict-aliasing -Xcompiler=-Wno-deprecated-declarations" \
  --cmake_extra_defines "onnxruntime_BUILD_UNIT_TESTS=OFF"

WHL="$(ls -1 build/Linux/Release/dist/onnxruntime_gpu-*-linux_aarch64.whl | head -1)"
echo "== built wheel: $WHL =="

# Install into the *active* venv (DriveAuth)
pip uninstall -y onnxruntime onnxruntime-gpu || true
pip install "$WHL"

# CRITICAL: leave the onnxruntime source tree — Python puts cwd on sys.path and
# will import the incomplete source package (no .capi) instead of the wheel.
cd "$ROOT"

"$PYTHON" - <<'PY'
import onnxruntime as ort
print("ORT", ort.__version__)
print("file", ort.__file__)
print("providers", ort.get_available_providers())
assert "onnxruntime" in ort.__file__ and "site-packages" in ort.__file__, (
    f"imported wrong package: {ort.__file__}"
)
assert "CUDAExecutionProvider" in ort.get_available_providers(), "CUDA EP missing"
print("CUDA EP OK")
PY

# Smoke MobileFaceNet if present
MFN="$ROOT/driveauth_store_phase2a/models/mobilefacenet.onnx"
if [[ ! -f "$MFN" ]]; then
  MFN="$ROOT/driveauth_store_phase2a/mobilefacenet.onnx"
fi
if [[ -f "$MFN" ]]; then
  "$PYTHON" - <<PY
import numpy as np
import onnxruntime as ort
print("using", ort.__file__)
sess = ort.InferenceSession(
    "$MFN",
    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
)
print("session providers", sess.get_providers())
inp = sess.get_inputs()[0]
blob = np.zeros((1, 3, 112, 112), dtype=np.float32)
sess.run(None, {inp.name: blob})
print("MobileFaceNet CUDA smoke OK")
PY
else
  echo "NOTE: no mobilefacenet.onnx under store — skip model smoke"
fi

echo
echo "SUCCESS. Next on Thor:"
echo "  unset DRIVEAUTH_ORT_PROVIDERS"
echo "  cd $ROOT && source .venv/bin/activate"
echo "  export DRIVEAUTH_USE_MOCK=0 DRIVEAUTH_STORE_DIR=\$PWD/driveauth_store_phase2a"
echo "  python scripts/phase2a_bench.py --store \"\$DRIVEAUTH_STORE_DIR\" \\"
echo "    --out phases/phase2a-thor.txt --device cuda --n 30"
echo
echo "Confirm face line uses CUDA (ORT providers include CUDAExecutionProvider)."
