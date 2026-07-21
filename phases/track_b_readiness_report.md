# Track B — Real `attack_side` Recapture + Stock-Bar Readiness (driver1 + driver7)

**Date:** 2026-07-21  
**Store:** `driveauth_store_phase2a`  
**Policy:** stock ladder only for the headline (V≥0.72 / F≥0.70) — **no** `phase2b_suggested.env` applied to decisions  
**Evidence:** `phases/driver1_e2e_audit.json`, `phases/driver7_e2e_audit.json`, `phases/track_b_live_pad.json`, `phases/track_b_logs/`  
**Constraints:** no commit/push; templates `faces/driver1.enc` / `faces/driver7.enc` untouched; per-driver Stage-2 paths only

---

## Final Verdict

**Neither driver is golden-reference under stock bars.** Real profile `attack_side` data is now in place and Stage-2 heads were retrained independently; absolute calibrated scores still miss 0.72 / 0.70, and PAD still false-accepts most Haar-OK real side poses.

| Driver | Policy | Genuine ACCEPT | Attack REJECT |
|--------|--------|----------------|---------------|
| **driver1** | Stock (V≥0.72 / F≥0.70) | **0 / 5 (0%)** | **14 / 14 (100%)** |
| **driver7** | Stock (V≥0.72 / F≥0.70) | **0 / 5 (0%)** | **14 / 14 (100%)** |

### Calibrated means vs stock

| Driver | Voice mean | vs 0.72 | Face mean | vs 0.70 | Voice ≥0.72 | Face ≥0.70 |
|--------|-----------:|--------:|----------:|--------:|------------:|-----------:|
| driver1 | **0.619** | **−0.101** | **0.571** | **−0.129** | **0 / 24** | **0 / 22** |
| driver7 | **0.552** | **−0.168** | **0.515** | **−0.185** | **0 / 8** | **0 / 10** |

---

## Phase 1 — real `attack_side` recapture

### Framing convention confirmed

| Driver | Target | Genuine baseline | Capture used |
|--------|--------|------------------|--------------|
| driver1 | 640×480, face_frac ≈0.35–0.40 | 22/22 Haar, mean frac **0.372** | 640×480 close-up |
| driver7 | 640×480 close-up (script); genuine face_frac ≈0.36 | 10/10 Haar, mean frac **0.362** (on-disk genuines still 1080p) | 640×480 close-up |

Old synth sides backed up under `data/*/face/attack_side_backup_synth_*` (driver7 was exact `synth_side` MSE=0).

### QC after capture

| Driver | n | Haar OK | Provenance (`synth_side` MSE) | Gate |
|--------|--:|--------:|-------------------------------|------|
| driver1 (1st try) | 10 | **1/10** | mean MSE≈4489, `looks_synth=False` | **RETAKE** |
| driver1 (retake) | 10 | **6/10 (60%)** | mean MSE≈4604, `looks_synth=False` | **PASS** |
| driver7 | 10 | **8/10 (80%)** | mean MSE≈4698, `looks_synth=False` | **PASS** |

Templates unchanged: `driver1.enc` 06:36:12 / `driver7.enc` 04:15:48.

---

## Phase 2 — Stage-2 retrain (per-driver paths only)

### LOO AUC

| Driver | `face_pad` | thr | APCER | `face_calibrator` | `voice_calibrator` |
|--------|----------:|----:|------:|------------------:|-------------------:|
| driver1 | **0.8107** | 0.46 | 0.240 | **0.9697** (gap +0.033) | **0.8237** (gap +0.033) |
| driver7 | **0.6962** | 0.48 | 0.385 | **0.8174** (gap +0.096) | **0.7750** (gap +0.174) |

### Live PAD (audit) + real `attack_side` FP

| Driver | Live PAD AUC (genuine+attack) | Attack-side FP | Fail-closed | Side pad mean |
|--------|------------------------------:|---------------:|------------:|--------------:|
| driver1 | **0.813** | **6 / 10 (60%)** | 4 / 10 | 0.554 |
| driver7 | **0.854** (audit) | **8 / 10 (80%)** | 2 / 10 | 0.580 |

Haar-OK real profiles still score as bonafide (~0.60–0.63 ≥ thr). Fail-closed only catches Haar-miss sides. **Real off-angle PA remains the soft spot** — this is the first honest test; synth warps never measured it.

### `stage2_status_for_driver()`

Both drivers, all three heads:

- `mode=per_driver`
- `training_origin=independent`
- paths under `faces/{id}/` / `voices/{id}/` only

### Overfit audit

| Driver | Result |
|--------|--------|
| driver1 | **OK / PASS** (voice / face_pad / face_cal / trust_fusion) |
| driver7 | **OK / PASS** (same; voice gap +0.174 noted but within auditor OK) |

---

## Phase 3 — stock-bar readiness (side by side)

Stock bars confirmed in audit JSON: `ladder_voice=0.72`, `ladder_face=0.70` (trust micro/std/high/reject stock). Demo bars were measured separately and are **not** the headline.

| | driver1 | driver7 |
|--|---------|---------|
| Genuine ACCEPT @ stock | **0 / 5** | **0 / 5** |
| Attack REJECT @ stock | **14 / 14** | **14 / 14** |
| Face cal AUC | 0.991 | 0.923 |
| Voice cal AUC | 0.775 | 0.900 |
| Raw face cosine g/a | 0.804 / 0.633 | 0.742 / 0.592 |
| Golden reference? | **No** | **No** |

Gap in score terms (not “close”): driver1 needs roughly **+0.10 voice** and **+0.13 face** on the calibrated means; driver7 needs roughly **+0.17 voice** and **+0.19 face**.

---

## What’s solid

| Area | Evidence |
|------|----------|
| Real `attack_side` | Provenance fails synth match (MSE ≫ 5); 640×480; Haar 6/10 and 8/10 after retake |
| Templates | Track A `*.enc` untouched |
| Stage-2 isolation | `independent` / `per_driver` for both drivers |
| Attack REJECT @ stock | **100%** both drivers |
| Face calibrator (driver1) | LOO **0.970**, live cal AUC **0.991** |
| Overfit | PASS both |
| Tests / lint | **344 passed**, 2 skipped; **ruff clean** |

---

## What still blocks golden-reference

1. **Stock ladder clearance** — calibrated means sit 0.10–0.19 below 0.72/0.70; **0** genuines clear either bar.
2. **Real side-pose PAD FPs** — 60% (d1) / 80% (d7) of new real `attack_side` still pass as live when Haar hits; only fallbacks fail-closed. PAD LOO for driver7 is weak (**0.696**).
3. **Score headroom** — even with good separation AUCs, absolute levels miss stock (especially driver7 voice mean **0.552**).
4. **Finger** — still no `fingers/{id}.enc`; 2-modality scope only.
5. **Shell env hygiene** — process env / prior demo sourcing can still trip the bar-override WARNING; stock audit path pops overrides and records stock bars, but live dashboard shells must not source `phase2b_suggested.env`.

---

## Phase 4 — suite

| Check | Result | vs prior baseline |
|-------|--------|-------------------|
| `pytest` | **344 passed**, **2 skipped** | Was 341 passed / 3 failed (AF_UNIX) then 332+skips; now clean with skip-gate |
| `ruff check .` | **clean** | unchanged |
| `overfit_audit_stage2` | PASS both drivers | — |

---

## Confirmation

- No `phase2b_suggested.env` applied to stock headline decisions.
- Wrote only `driveauth_store_phase2a/faces/{driver1,driver7}/*` and `voices/{driver1,driver7}/*` Stage-2 artifacts.
- Face templates `driver1.enc` / `driver7.enc` not modified.
- `scripts/audit_driver1_e2e.py` gained `--driver-id` (driver7 → `phases/driver7_e2e_audit.json`).
- Uncommitted for your review.
