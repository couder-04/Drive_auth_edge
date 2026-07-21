# Driver1 End-to-End Readiness Audit (post re-capture + retrain)

**Date:** 2026-07-21  
**Store:** `driveauth_store_phase2a`  
**Data:** `data/driver1` (new genuine face×22 + voice×24; enroll/attacks unchanged)  
**Policy:** stock ladder only for the headline (V≥0.72 / F≥0.70) — no `phase2b_suggested.env` applied to decisions  
**Evidence:** `phases/driver1_e2e_audit.json`, `phases/driver1_pad_haar_diagnosis.json`  
**Constraints:** no commit/push; driver7 untouched; per-driver paths only

---

## Final Verdict

**Not golden-reference under stock bars.** Capture + PAD pipeline fixes worked; absolute score levels still miss the stock ladder.

| Policy | Genuine ACCEPT | Attack REJECT |
|--------|----------------|---------------|
| Stock ladder (V≥0.72 / F≥0.70) | **0 / 5 (0%)** | **14 / 14 (100%)** |

Calibrated means vs stock: voice **0.619** (−0.101 vs 0.72), face **0.586** (−0.114 vs 0.70).  
**0 / 22** face genuines ≥ 0.70; **0 / 24** voice genuines ≥ 0.72.

---

## What’s solid

| Area | Evidence |
|------|----------|
| Prerequisite fixes | Fallback meta honest; PAD fail-closed on Haar miss; 640×480 capture gate |
| New face genuines | **22/22 Haar OK (100%)**, all 640×480, face_frac mean **0.372** (was 3/20 / ~15% far-field) |
| New voice genuines | **24/24** `score_voice()` OK; ~3.2 s; sample q≈1.0 |
| Overall Haar detect | **92.5%** (49/53) vs old **58.8%** (30/51); only 4 fallbacks (all `attack_side`) |
| Stage-2 paths | All three heads → `faces/driver1/` / `voices/driver1/`; `mode=per_driver`; `training_origin=independent` |
| PAD live vs LOO | LOO **0.823**; live genuine+attack AUC **0.895** (was **0.652**) — gap **closed / inverted** |
| Overfit audit | **PASS** (voice/face_pad/face_cal/trust_fusion) |
| Attack REJECT @ stock | **100%** |

### LOO AUCs (retrain)

| Head | LOO AUC | Notes |
|------|--------:|-------|
| `face_pad` | **0.8228** | n=49; excluded 4 fallback sides; thr=0.32; APCER=0.211 |
| `face_calibrator` | **0.8158** | n=41; gap=+0.074 |
| `voice_calibrator` | **0.8237** | n=37; gap=+0.033 |

### Live PAD slices (same diagnostic as before)

| Slice | n | AUC |
|-------|--:|----:|
| Genuine+attack (live) | 45 | **0.895** |
| Haar-OK / train-set | 49 | **0.881** |
| All samples (incl enroll) | 53 | **0.901** |
| Fallback-only | 4 | n/a (attacks only; all `pad_reject`) |

Parity mismatches: **0**. Fallback feature `face_frac` mean: **0.0** (no fabricated 1.0).

---

## What still blocks golden-reference

1. **Stock ladder clearance** — voice/face calibrated means sit ~0.10 below 0.72/0.70; ladder never early-stops ACCEPT on genuines.
2. **Raw face cosine still weak / inverted** — genuine mean **0.366** vs attack **0.399** (cosine AUC **0.211**). Calibrator+PAD separate classes (cal AUC **0.881**), but identity match to the *existing* enroll template did not jump with re-capture. Re-enrolling the face template from the new close-up set (or expanding enroll) is the likely next lever — **not** lowering bars.
3. **PAD APCER / side FPs** — confusion still **FP=8** on raw PAD thr (Haar-OK `attack_side`); 4 fallback sides fail-closed. Side presentation attacks remain the soft spot.
4. **Finger** — still no `fingers/driver1.enc` / FingerNet; stage-3 unavailable.
5. **`secrets.env` still contains demo bar overrides** — audit stock path uses explicit stock bars (0.72/0.70), but any live dashboard shell sourcing that env is **not** stock. Unset those for production honesty.

---

## Tests / lint

| Check | Result |
|-------|--------|
| `overfit_audit_stage2.py --driver-id driver1` | **OK / PASS** |
| `pytest` | **341 passed**, 2 skipped, **3 failed** (`FingerDaemon` unix-socket bind — sandbox/`Operation not permitted`; not driver1 bio regressions) |
| `ruff check .` | **clean** after trivial E741 fix in diagnose script |

---

## Confirmation

- No driver7 data/heads touched.
- Wrote only `driveauth_store_phase2a/faces/driver1/*` and `voices/driver1/*`.
- No `phase2b_suggested.env` applied to the stock headline.
- Uncommitted for your review.
