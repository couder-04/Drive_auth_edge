#!/usr/bin/env bash
# Register a self-hosted GitHub Actions runner for DriveAuth HIL tests.
#
# Prerequisites on the host:
#   - BlueZ (Bluetooth), optional HailoRT
#   - Python 3.11+, git
#   - GitHub repo admin access to obtain a registration token
#
# Usage:
#   export GITHUB_REPO=owner/Drive_auth_edge
#   export RUNNER_TOKEN=<from GitHub Settings → Actions → Runners → New>
#   ./scripts/setup_hil_runner.sh

set -euo pipefail

REPO="${GITHUB_REPO:-}"
TOKEN="${RUNNER_TOKEN:-}"
RUNNER_NAME="${RUNNER_NAME:-driveauth-hw-$(hostname -s)}"
LABELS="${RUNNER_LABELS:-self-hosted,driveauth-hw}"

if [[ -z "$REPO" || -z "$TOKEN" ]]; then
  echo "Set GITHUB_REPO and RUNNER_TOKEN before running." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner-driveauth}"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ ! -f ./config.sh ]]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) RUNNER_ARCH=x64 ;;
    aarch64|arm64) RUNNER_ARCH=arm64 ;;
    *) echo "unsupported arch: $ARCH" >&2; exit 1 ;;
  esac
  curl -fsSL -o actions-runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-${RUNNER_ARCH}-2.321.0.tar.gz"
  tar xzf actions-runner.tar.gz
fi

./config.sh --url "https://github.com/${REPO}" --token "$TOKEN" \
  --name "$RUNNER_NAME" --labels "$LABELS" --unattended

echo "Installing Python deps from $ROOT ..."
python3 -m pip install -e "${ROOT}[dev,hardware,bluetooth,face]"

sudo ./svc.sh install || ./run.sh &
echo "Runner registered. Trigger .github/workflows/hardware-hil.yml via workflow_dispatch."
