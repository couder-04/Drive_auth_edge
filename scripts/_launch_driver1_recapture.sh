#!/bin/zsh
cd /Users/par_04/Desktop/staged_driveauth-edge || exit 1
source .venv/bin/activate
set -a && source secrets.env && set +a
echo "=== Driver1 genuine re-capture ==="
echo "Face: 22 auto Haar-OK stills at 640x480 (fill green oval, hold still)."
echo "Voice: 24 clips x ~3.5s (Enter before each phrase)."
echo "q quits face early. Camera Privacy must allow Terminal."
echo
python scripts/recapture_driver1_genuine.py --face-n 22 --voice-n 24 --camera 0
ec=$?
echo
echo "Exit code: $ec"
echo "Press Enter to close…"
read
exit $ec
