#!/usr/bin/env sh
# Idempotent first-boot for Railway / Docker cloud image.
# Ensures /data layout exists and seeds the store if the volume is empty.
set -eu

STORE="${DRIVEAUTH_DASHBOARD_STORE:-/data/store}"
DATA="${DRIVEAUTH_DATA_ROOT:-/data/data}"
SEED="${DRIVEAUTH_STORE_SEED:-/app/driveauth_store_pha}"

mkdir -p "$STORE" "$DATA" /data/hf /data/torch /data/perf \
  "$STORE/audit" "$STORE/fleet_telemetry"

# Seed bundled Phase-2a store when volume is fresh (no face model).
if [ ! -f "$STORE/mobilefacenet.onnx" ] && [ ! -f "$STORE/models/mobilefacenet.onnx" ]; then
  if [ -d "$SEED" ]; then
    echo "railway_first_boot: seeding store from $SEED -> $STORE"
    cp -a "$SEED/." "$STORE/"
  else
    echo "railway_first_boot: no seed dir at $SEED — run phase2a_setup on volume"
  fi
fi

# Optional: verify bootstrap checklist (non-fatal — dashboard may still serve mock).
if command -v python >/dev/null 2>&1; then
  python scripts/bootstrap.py --store "$STORE" --check-only || \
    echo "railway_first_boot: bootstrap check reported gaps (see logs)"
fi

echo "railway_first_boot: ready store=$STORE data=$DATA"
