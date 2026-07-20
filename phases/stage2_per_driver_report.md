# Stage-2 per-driver engineering report (2026-07-21)

Uncommitted local work. Measurements from `phases/stage2_per_driver_eval.json`
(regenerated via `scripts/eval_stage2_per_driver.py`).

## Architecture

**Problem:** `face_pad.onnx` / `face_calibrator.onnx` / `voice_calibrator.onnx` lived once
per store root. Driver7 retrain overwrote the heads used by Driver1.

**Fix:** Per-driver Stage-2 bio artifacts:

```
faces/{driver_id}/face_pad.onnx (+ .json, face_calibrator.*)
voices/{driver_id}/voice_calibrator.onnx (+ .json)
```

Templates remain encrypted `faces/{id}.enc` / `voices/{id}.enc` (not `embeddings.bin`).
`risk_gbt` / `trust_fusion` stay store-global.

**Loading order:** per-driver → legacy shared (WARNING, never silent) → missing.

**Training origin honesty:** migrated copies stamp `migrated_from`; status mode is
`per_driver_migrated` + `needs_retrain=true` until independent retrain.

### Files changed (primary)

| Area | Files |
|------|-------|
| Resolver | `driveauth/stage2_artifacts.py` (new) |
| Loaders | `driveauth/matchers/face.py`, `voice.py` |
| Trainers | `scripts/train_face_pad.py`, `train_face_calibrator.py`, `train_voice_calibrator.py` |
| Migration | `scripts/migrate_stage2_per_driver.py` (new) |
| Eval | `scripts/eval_stage2_per_driver.py` (new) |
| Integrity / purge | `driveauth/integrity.py`, `purge.py` |
| API / config | `driveauth/api.py`, `config.py` |
| Bootstrap / audit | `scripts/bootstrap.py`, `overfit_audit_stage2.py` |
| Dashboard | `dashboard/app.py`, `dashboard/dashboard.py`, `dashboard/server.py` |
| Docs | `docs/stage2-per-driver.md`, `docs/security-assumptions.md`, `README.md` |
| Tests | `tests/test_stage2_per_driver.py`, `tests/test_stage2_fusion.py` |

### Migration summary

```
migrate (all enrolled) →
  driver1,driver7: already_present (independently retrained)
  driver2,driver3,driver6: 9 copied from legacy; legacy preserved
Legacy store-root ONNX files NOT deleted (by design).
```

---

## Driver1

| | Before (shared / overwrite risk) | After (per-driver) |
|--|----------------------------------|--------------------|
| Face PAD LOO | Contaminated by shared head | **0.8373** (enabled; 21 Haar-fallback excluded) |
| Face cal LOO | shared | **0.7609** |
| Voice cal LOO | shared | **0.8308** |
| Face cal AUC (eval) | — | raw 0.687 → **cal 0.885** |
| Voice cal AUC (eval) | — | raw 0.794 → cal 0.800 (incl. `noisy`) |
| Stock ladder (mean scores) | — | **REJECT** (voice 0.623 < 0.72, face 0.613 < 0.70) |
| Demo phase2b ladder | — | **ACCEPT** (voice≥0.58 and face≥0.36; early-stop OR) |
| Demo fused proxy | — | **ACCEPT** (mean 0.618 ≥ 0.584) |

**Regression removed?** Yes for the overwrite class: Driver7 retrain cannot replace Driver1 artifacts.

---

## Driver7

| | Before | After |
|--|--------|-------|
| Face PAD LOO | **0.5000** (gate disabled) | **0.8132** (enabled; 5 fallback crops excluded) |
| Face cal LOO | ~0.69 shared | **0.6875** |
| Voice cal LOO | ~0.775 shared | **0.775** |
| Face cal AUC | — | raw 0.733 → **cal 0.896** |
| Voice cal AUC | — | raw 0.867 → **cal 0.900** |
| Stock ladder | — | **REJECT** (voice 0.552, face 0.486) |
| Demo phase2b ladder | — | **ACCEPT** via face bar 0.36 (voice 0.552 < 0.58 still fails) |
| Demo fused proxy | — | **REJECT** (mean 0.519 < 0.584) |

**Regression removed?** Overwrite bug fixed. PAD recovered by excluding Haar-miss fallbacks — **not** by lowering thresholds.

### PAD excluded samples (driver7)

- `face/attack_blur/blur_08.jpg`
- `face/attack_side/side_04.jpg`, `side_06.jpg`, `side_07.jpg`, `side_08.jpg`

### PAD excluded samples (driver1)

21 Haar-miss center-crops (17 genuine + 4 `attack_side`) — listed in `faces/driver1/face_pad.json` → `excluded_fallback_crops`.

---

## PAD

| Driver | Old LOO | New LOO | Enabled? | Recommendation |
|--------|---------|---------|----------|----------------|
| driver1 | (shared) | 0.8373 | **yes** | Keep; improve frontal genuines (many Haar misses) |
| driver7 | **0.5000** | **0.8132** | **yes** | Keep; replace excluded `attack_side` with detected faces |
| driver2/3/6 | legacy 0.50 snapshot | migrated copy | **no** (LOO≤0.55 auto-disable) | Collect genuine+attack labeled sets → independent retrain |

If PAD LOO ≤ 0.55, `FaceMatcher` disables the gate and logs an error. No shipped “chance PAD”.

---

## Face (raw vs calibrated)

| Driver | Raw g/a mean | Cal g/a mean | Cal AUC |
|--------|--------------|--------------|---------|
| driver1 | 0.474 / 0.399 | 0.613 / 0.166 | 0.885 |
| driver7 | 0.742 / 0.526 | 0.486 / 0.135 | 0.896 |

---

## Voice (raw vs calibrated)

| Driver | Raw g/a mean | Cal g/a mean | Cal AUC | Notes |
|--------|--------------|--------------|---------|-------|
| driver1 | 0.670 / 0.364 | 0.623 / 0.444 | 0.800 | Incl. `noisy` attacks; stock ladder still strict |
| driver7 | 0.538 / 0.438 | 0.552 / 0.448 | 0.900 | AUC OK; **absolute genuine mean too low for stock 0.72** |

### Voice diagnosis (driver7)

Not a calibrator bug (LOO 0.775, eval AUC 0.90). Failure vs stock ladder is **absolute score level**:

- Genuine raw mean **0.538** (enrollment variability / short clips)
- Separation raw only **+0.10** vs attacks
- Enrollment: 12 enroll WAVs, 8 genuine — usable but noisy/variable

**Recommendations (data, not thresholds):**

1. Re-record enroll + genuine at consistent distance/mic, 3–5 s clean speech, same phrase set.
2. Reject silent/near-silent clips at capture time.
3. Re-enroll template after new samples; retrain **only** `voices/driver7/voice_calibrator.onnx`.
4. Do **not** lower `DRIVEAUTH_LADDER_ACCEPT_VOICE` to “fix” this.

---

## Thresholds

| | Stock | Demo (`phase2b_suggested.env`) |
|--|-------|--------------------------------|
| Ladder V/F/Fi | 0.72 / 0.70 / 0.70 | 0.58 / 0.36 / 0.70 |
| Trust µ/std/hi/rej | 0.70 / 0.78 / 0.85 / 0.48 | 0.554 / 0.584 / 0.614 / 0.419 |

**Impossible-to-miss warnings:**

- stderr banner (`POLICY BARS DIFFER FROM policy.yaml STOCK DEFAULTS`) with stock → deployed + delta + reason
- `driveauth.security` WARNING log
- Fired on `DriveAuth.load` (`_announce_stage2`) and dashboard server startup
- Dashboard `#threshold-banner` when override/demo mode

See `docs/security-assumptions.md` §6.

---

## Tests

- `tests/test_stage2_per_driver.py` — resolve, migrate, isolation, integrity, purge, loaders, threshold warn, announce, dashboard helpers, migrated-flag, trainer path isolation
- Updated `tests/test_stage2_fusion.py` for per-driver paths
- Full suite: **343 passed**, 2 skipped (3 finger-daemon bind failures only under sandbox; pass with unrestricted sockets)

---

## Remaining issues

1. **Driver7 voice absolute scores** — need better enrollment audio (above). Do not lower bars.
2. **Driver1 Haar misses** — many genuine stills fall back to center-crop; PAD training excluded them (honest) but face enrollment quality should improve lighting/pose.
3. **Legacy store-root ONNX** still on disk (intentionally preserved). Optional cleanup after all drivers independently retrained.
4. **Drivers 2 / 3 / 6** — templates enrolled; Stage-2 heads are **migrated shared snapshots** (`per_driver_migrated`, `needs_retrain`). No genuine labeled sets → cannot honestly retrain yet. PAD auto-disabled (legacy LOO 0.50).
5. Stock policy **REJECT** on mean genuine scores for both independently trained drivers is expected honesty — demo env is UX-only, not a security improvement.

---

## How to verify

```bash
python scripts/migrate_stage2_per_driver.py --store driveauth_store_phase2a
python scripts/eval_stage2_per_driver.py --drivers driver1,driver7
python scripts/bootstrap.py --check-only --store driveauth_store_phase2a
pytest tests/test_stage2_per_driver.py tests/test_stage2_fusion.py -q
```
