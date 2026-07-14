# Phase 1 — Edge deployment (complete)

**Status:** ✅ Done (2026-07-12)  
**Scope:** Mock pipeline on Mac (1a) + NVIDIA Thor (1b). Real ECAPA/face on Thor is **optional Phase 2a**, not required for Phase 1.

## Done means (from roadmap)

| Criterion | Evidence |
|-----------|----------|
| Thor install + deps + GPU visible | `phases/thor.txt` — Tegra Linux, ORT, nvidia-smi “NVIDIA Thor” |
| End-to-end demo on device | pytest 50✓ · `driveauth-demo` ACCEPT · dashboard `:8765` · audit log |
| Hardware profile captured | `phases/mac.txt` + `phases/thor.txt` |
| p95 latency &lt; policy budget | mock auth **p95 ≤ 10 ms** (below) |

## Latency budget (Phase 1 — mock auth)

| Budget | Value | Rationale |
|--------|-------|-----------|
| `MOCK_AUTH_P95_MS` | **10 ms** | Decision path with mock matchers must stay interactive; leaves headroom before constant-time pad / real models |

| Platform | Profile | p50 | p95 | max | vs 10 ms budget |
|----------|---------|-----|-----|-----|-----------------|
| Mac M4 (1a) | `phases/mac.txt` | 0.7 ms | **0.8 ms** | 9.6 ms | ✅ PASS |
| NVIDIA Thor (1b) | `phases/thor.txt` | 0.6 ms | **0.9 ms** | 8.6 ms | ✅ PASS |

Bench note: `phase1b_thor_bench.py` warms up 5 auths before measuring so cold-start
spikes don’t dominate p95.

Real ECAPA on Mac (Phase 2a, not Phase 1): p95 ≈ 35 ms — separate budget when profiling 2a on Thor.

## Artifacts

| File | Role |
|------|------|
| [`mac.txt`](mac.txt) | Phase 1a Mac baseline |
| [`thor.txt`](thor.txt) | Phase 1b Thor profile + pass checklist |
| [`thor.md`](thor.md) | How to re-run 1b on a fresh board |
| [`../scripts/phase1b_thor_bootstrap.sh`](../scripts/phase1b_thor_bootstrap.sh) | One-shot install · test · demo · bench |
| [`../scripts/phase1b_thor_bench.py`](../scripts/phase1b_thor_bench.py) | Writes / refreshes `thor.txt` |

## Re-run on Thor

```bash
bash scripts/phase1b_thor_bootstrap.sh
driveauth-dashboard   # DRIVEAUTH_DASHBOARD_HOST=0.0.0.0
# Mac: ssh -L 8765:127.0.0.1:8765 … then http://127.0.0.1:8765
```

## Out of scope (later)

- Finger SDK / real CAN / live Nova GPS
- Phase 2a voice+face latency on Thor GPU EP
- Whole-pipeline latency optimisation (wait for 2a Thor profile)
