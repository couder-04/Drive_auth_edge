#!/usr/bin/env bash
# Quick checks before a live demo (mock path — must ACCEPT).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export DRIVEAUTH_USE_MOCK=1
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0

echo "== pytest =="
pytest -q

echo "== mock demo (expect ACCEPT) =="
OUT="$(driveauth-demo 2>&1)"
echo "$OUT"
echo "$OUT" | grep -q "Decision:.*ACCEPT" || {
  echo "FAIL: expected ACCEPT from driveauth-demo" >&2
  exit 1
}

echo
echo "== demo assets =="
test -f README.md && echo "  README.md OK"
test -f roadmap-2026-07.md && echo "  roadmap-2026-07.md OK"
test -f phases/mac.txt && echo "  phases/mac.txt OK"
test -f phases/thor.txt && echo "  phases/thor.txt OK"
test -f phases/phase1.md && echo "  phases/phase1.md OK"
test -f data/driver1/transaction/txns.csv && echo "  txns.csv OK"
echo "  voice wavs: $(find data/driver1/voice -name '*.wav' | wc -l | tr -d ' ')"
echo "  face jpgs:  $(find data/driver1/face -name '*.jpg' | wc -l | tr -d ' ')"

echo
echo "Preflight OK — mock path ready. See roadmap-2026-07.md for next steps."
echo "Thor dashboard (optional): ssh -p 10617 -L 8765:127.0.0.1:8765 acf-thor@fw1.sshreachme-trial.com"
echo "  then open http://127.0.0.1:8765"
