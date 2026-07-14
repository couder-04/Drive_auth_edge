# Phase 1b — NVIDIA Thor (mock pipeline on-device)

**Status:** ✅ Complete (2026-07-12) — see [`phase1.md`](phase1.md) and results in [`thor.txt`](thor.txt).

**Goal:** same Mac Phase 1a baseline on Thor — mock matchers, pytest, demo, dashboard, latency → `phases/thor.txt`.

**Out of scope for 1b:** ECAPA / MobileFaceNet / finger SDK (optional Phase 2a on Thor after this).

## Checklist

| Step | Action | Done? |
|------|--------|-------|
| 1 | SSH + disk OK | ✅ |
| 2 | Clone/copy repo · Python 3.12 · `pip install -e ".[dev,dashboard,onnx]"` | ✅ |
| 3 | `pytest` · `DRIVEAUTH_USE_MOCK=1 driveauth-demo` | ✅ |
| 4 | Dashboard `0.0.0.0:8765` · ACCEPT micro · audit grows | ✅ |
| 5 | Print ORT providers (CPU EP for mock) | ✅ |
| 6 | `python scripts/phase1b_thor_bench.py` → `phases/thor.txt` | ✅ |
| 7 | Optional 30 min soak | ⬜ optional / not required |

## On Thor (fresh board)

```bash
cd staged_driveauth-edge   # or your path
bash scripts/phase1b_thor_bootstrap.sh

# or manually:
python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,dashboard,onnx]"

export DRIVEAUTH_STORE_DIR="${DRIVEAUTH_STORE_DIR:-$HOME/driveauth_store}"
mkdir -p "$DRIVEAUTH_STORE_DIR"
export DRIVEAUTH_USE_MOCK=1
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0
export DRIVEAUTH_DASHBOARD_HOST=0.0.0.0
export DRIVEAUTH_DASHBOARD_PORT=8765

pytest -q
driveauth-demo
python scripts/phase1b_thor_bench.py --out phases/thor.txt
driveauth-dashboard
```

ORT providers smoke:

```bash
python - <<'PY'
import onnxruntime as ort
print("ORT", ort.__version__)
print("providers", ort.get_available_providers())
PY
```

## Pass criteria

- Import `driveauth` works
- pytest green
- Demo ACCEPT on micro path
- `phases/thor.txt` filled (compare p50 to Mac `phases/mac.txt` ≈ 0.7 ms mock)
- Mock auth **p95 ≤ 10 ms** (Phase 1 budget — see `phase1.md`)
- Providers listed (CPU for mock; CUDA/TensorRT when stack is ready for 2a)

## After 1b

Optional: run Phase 2a scripts on Thor (`pip install -e ".[voice,face,onnx,dev]"` + `phase2a_setup/enroll/demo`) for edge latency with real ECAPA/face.
