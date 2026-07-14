# Phase 5 — Testing (Stage 3 complete)

**Exit:** 150+ tests; timing + OOD + real-model failures covered. ✅

| Gate | Evidence |
|---|---|
| Timing side-channel | `tests/test_security_sprint1.py` — `ESCALATION_CONSTANT_TIME_MS` pad |
| OOD-drift defence | `tests/test_security_sprint1.py` + `tests/test_ood_stage1.py` |
| Threshold re-baseline | `tests/test_phase5_thresholds.py` vs `phases/phase2b_calibration.json` / `phase2b_bio_eval.json` |
| Real-model failure modes | `tests/test_phase5_failure_modes.py` — crash / timeout / missing sensors |
| Suite size | **155** collected (`pytest tests/ -q`) |

## Threshold re-baseline (conservative)

Real-model voice genuine p50 sits **below** mock-era 0.9 scores (~0.61–0.68 after Stage 2). Calibration writes `phases/phase2b_calibration.json` + optional `phase2b_suggested.env`.

**Shipped policy stays strict** — do **not** source `phase2b_suggested.env` while face attack overlap keeps face FAR=0 FRR≈1.0. Ladder voice bar (≥ FAR=0 suggestion) remains the early-accept floor; lower fused trust bars are suggested only.

## Failure-mode hardening

`DecisionEngine` now:

- Catches matcher / behavioral crashes → modality `available=False`
- Runs each ladder probe under `CAPTURE_JOIN_TIMEOUT_S` (default 6s)
- Rejects NaN modality scores in `LadderPlan.is_accept`

## Re-run

```bash
pytest tests/ -q
python scripts/calibrate_bio_thresholds.py --store ./driveauth_store_phase2a
```
