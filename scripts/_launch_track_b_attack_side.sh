#!/bin/zsh
# Track B — real attack_side recapture (interactive camera).
# Usage: scripts/_launch_track_b_attack_side.sh driver1|driver7
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
source .venv/bin/activate

DRIVER="${1:-driver1}"
N="${2:-10}"

echo "=============================================="
echo " Track B — ${DRIVER} REAL attack_side"
echo "=============================================="
echo "Convention: 640×480 close-up (same distance as genuines)."
echo "  driver1 genuine face_frac mean≈0.372"
echo "  driver7 genuine face_frac mean≈0.362"
echo "Pose: clear PROFILE / >45° yaw — alternate LEFT and RIGHT."
echo "Lighting: same session quality as that driver's genuine set."
echo "Keys: SPACE=save · q=quit. Face gate optional (warn only)."
echo "Target: ${N} stills. Prefer ¾ profile so Haar can still hit."
echo
echo "Writing into: data/${DRIVER}/face/attack_side/"
ls data/"${DRIVER}"/face/attack_side/ 2>/dev/null || true
echo

python scripts/capture_own_face.py \
  --driver-id "${DRIVER}" \
  --split attack_side \
  --n "${N}" \
  --camera 0

echo
echo "Done. Next: ask the agent to run Haar + provenance QC."
echo "Press Enter to close…"
read -r _
