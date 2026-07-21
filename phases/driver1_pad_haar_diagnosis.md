# Driver1 PAD Live-vs-Training Gap & Haar Detection Diagnosis

**Date:** 2026-07-21  
**Store:** `driveauth_store_phase2a`  
**Data:** `data/driver1`  
**Evidence:** `phases/driver1_pad_haar_diagnosis.json` (from `scripts/diagnose_driver1_pad_haar.py`)  
**Constraints honored:** no retrain, no threshold/policy edits, no commit/push

---

## Final Recommendation

**3. Both are required.**

| Why code first is insufficient | Why data first is insufficient |
|--------------------------------|--------------------------------|
| Fallback path still lies to PAD (`face_frac=1.0`, `frontal_ok=True`) and **inverts** attack/genuine ranking on Haar-miss frames | 17/20 genuines are 1080p far-field (`face_frac≈0.05–0.12`) vs enroll at 640×480 close-up (`face_frac≈0.39–0.50`) |
| Softening Haar alone raises detect rate 58.8%→84.3% but does not fix distance/blur quality for embedding | New close frontal genuines collected into the current fallback meta bug will still poison live PAD whenever Haar misses |

Fix the fallback→PAD contract, then re-collect genuines at enroll framing (or closer). Do not retrain until both are done.

---

## PAD

### Metrics

| Metric | Value | Notes |
|--------|------:|-------|
| Training LOO AUC | **0.837** | On n=30 Haar-OK samples (`--exclude-fallback-crops`) |
| Training fit-all AUC | 0.938 | Same 30 files, in-sample |
| Live eval AUC (genuine+attack) | **0.652** | n=43; matches e2e audit |
| Live AUC on **train-set only** | **0.938** | Same pipeline, same 30 files |
| Live AUC on **fallback-only** | **0.000** | n=21; attacks outscore genuines |
| False positives | **8** | All 8 are `attack_side/*` |
| False negatives | 0 | At thr=0.39 |

### Pipeline parity (train vs live)

Traced end-to-end on all 51 stills:

| Stage | Train (`capture_frame` + `extract_face_pad_features`) | Live (`capture_and_score` → `_run_pad`) | Match? |
|-------|------------------------------------------------------|------------------------------------------|--------|
| Crop | Haar padded box or center square | Identical | **YES** |
| Resize / color / normalize (PAD feats) | Hand-crafted on crop BGR | Same function | **YES** |
| Feature vector (8-D) | `FACE_PAD_FEATURE_KEYS` | Same | **YES** (max Δ = 0) |
| ONNX input | N/A at train extract; scored with live head | `faces/driver1/face_pad.onnx` | **YES** |
| PAD score | Same ONNX head | Same | **YES** (max Δ = 0) |
| Threshold | 0.39 from meta | 0.39 from meta | **YES** |
| Calibration | Not part of PAD score | Face calibrator separate | N/A for PAD AUC |

**Parity result: 0 / 51 mismatches.** The prior `capture_and_score` vs `capture_frame` meta bug is fixed. No remaining train/serve feature mismatch.

### Runtime configuration

| Check | Result |
|-------|--------|
| Model path | `faces/driver1/face_pad.onnx` (per_driver) |
| Legacy root ONNX present | yes, **not used** |
| PAD enabled | true (LOO 0.837 > 0.55) |
| Threshold | 0.39 |
| ORT providers (PAD) | CPUExecutionProvider |
| ORT providers (MobileFaceNet) | CoreML + CPU |

Live loads exactly the Driver1 PAD head used in training meta.

### Explanation of 0.837 → 0.652 gap

**Not** pipeline mismatch. **Not** calibration mismatch (PAD AUC is raw PAD proba). **Not** ORT/provider drift.

**Primary cause: evaluation-set / domain shift from Haar fallback crops.**

1. Training excluded 21 fallback crops (17 genuine + 4 side). LOO=0.837 is on the easy Haar-OK subset only.
2. Live eval scores all genuines+attacks, including those 21. On fallback frames the matcher sets `face_frac=1.0` and `frontal_ok=True`, so PAD sees a full-frame “face.”
3. Measured slices (same live code path):

| Slice | n | AUC |
|-------|--:|----:|
| Train-set / Haar-OK only | 30 | **0.938** |
| Genuine+attack (live eval) | 43 | **0.652** |
| Fallback-only | 21 | **0.000** |

4. Feature means confirm the lie: fallback `face_frac` mean = **1.0** vs Haar-OK mean **0.429**.
5. All 8 FPs are `attack_side`. Side poses (Haar-OK or fallback) score ~0.60 ≥ 0.39. Blur/screen are rejected. LOO APCER 0.21 already flagged side weakness; live just adds 4 more side fallbacks.

**Secondary:** statistical optimism of LOO vs tiny n_pos=11; LOO 0.837 vs fit-all 0.938 is expected. The 0.18 live drop vs LOO is almost entirely the fallback/domain mix, not variance alone.

### Recommended code changes (do not apply thresholds/policy)

1. **Stop lying on fallback meta.** On `inject_fallback`, set `face_frac` low (e.g. measured or ≤0.25) and/or `frontal_ok=False` — never `face_frac=1.0` + `frontal_ok=True`.
2. **Prefer fail-closed for PAD on fallback** during auth (no center-crop bonafide score), or skip PAD and force quality reject — center-crop currently helps attacks more than genuines (fallback AUC=0).
3. Optional: soften Haar (`scaleFactor=1.03`, `minNeighbors=3`, `minSize=(20,20)`) — raises detect rate to ~84% under current gates; validate false-box rate before shipping.
4. Do **not** retrain PAD until genuines are re-captured at enroll framing and fallback contract is fixed.

---

## Haar

### Detection summary

| Metric | Value |
|--------|------:|
| Detection rate (prod) | **58.8%** (30/51) |
| Fallback crops | **21** |
| Cascade | `haarcascade_frontalface_default.xml` |
| Prod params | scaleFactor=1.1, minNeighbors=5, minSize=default |
| Frontal gates | face_min_frac=0.18, cx∈[0.25,0.75], aspect∈[0.65,1.35] |

### Root-cause distribution (21 fallbacks)

| Category | Count | Interpretation |
|----------|------:|----------------|
| `face_too_small_frac` (&lt;0.18) | **9** | Cascade finds a face, but subject too far (frac 0.05–0.12) |
| `cascade_no_detection+blur` | **7** | No box; Laplacian var ~24–39 |
| `cascade_no_detection` (side / clear) | **5** | 4× `attack_side` + 1 genuine; frontal cascade limitation |

**Composition of failures:** **E — combination**, dominated by **A (bad/far enrollment genuine data)** + **B (detector config too strict for 1080p far faces)** + cascade limitation on true side poses. Not a software bug in the crop math; not a camera-index bug (stills).

Critical framing mismatch:

| Set | Resolution | Haar OK | Typical face_frac |
|-----|------------|--------:|------------------:|
| enroll | **640×480** | 8/8 | 0.39–0.50 |
| genuine | **1920×1080** | 3/20 | fail 0.05–0.12 |
| attack_blur | 640×480 | 8/8 | — |
| attack_side | 640×480 | 4/8 | — |
| attack_replay_screen | 1920×1080 | 7/7 | — |

### Fallback crop vs expected crop

When Haar misses or fails gates, live uses a **min-side center square** and tells PAD `face_frac=1.0`. For the 9 too-far genuines, a real (small) face box exists but is discarded; the center crop dilutes the face and invents a perfect face fraction. That is why fallback PAD features are not comparable to training crops.

### Parameter sensitivity (gates unchanged)

| scaleFactor | minNeighbors | minSize | Gate pass rate |
|------------:|-------------:|---------|---------------:|
| **1.03** | **3** | **(20,20)** | **84.3%** |
| 1.05 | 2 | (20,20) | 82.4% |
| 1.05 | 3 | (30,30) | 74.5% |
| **1.1 (prod)** | **5** | default | **58.8%** |
| 1.15 | 5 | default | 51.0% |

Relaxing frontal gates alone with prod cascade: no gain until gates removed entirely (58.8%→76.5%). Softening `face_min_frac` to 0.12 does **not** help — failing faces are already ≤0.12.

**Parameter change alone significantly improves detection (≈+25 pp).** Recommended experiment (not applied): `scaleFactor=1.03`, `minNeighbors=3`, `minSize=(20,20)`.

**But** re-enrollment is still required: even at 84% detect, far 1080p genuines remain out-of-distribution vs 640×480 enroll templates, and soft blur (mean Laplacian ~35 on fallback genuines) remains.

### Representative failed images

| File | Size | Face size | Bright | Blur (Lap var) | Pose / reason |
|------|------|-----------|-------:|---------------:|---------------|
| genuine_09.jpg | 1920×1080 | ~52×52 | 155 | 35 | too_far frac=0.048 |
| genuine_18.jpg | 1920×1080 | ~64×64 | 154 | 38 | too_far frac=0.059 |
| genuine_05.jpg | 1920×1080 | ~116×116 | 154 | 28 | too_far frac=0.107 |
| genuine_01.jpg | 1920×1080 | — | 154 | 39 | cascade miss + blur |
| genuine_20.jpg | 1920×1080 | ~128×128 | 147 | 24 | too_far frac=0.119 |
| side_01.jpg | 640×480 | — | 153 | 339 | cascade limitation (profile) |

Full 21-row table: `phases/driver1_pad_haar_diagnosis.json` → `haar.fallback_images`.

---

## Final Recommendation (evidence)

**Choose: 3. Both are required.**

1. **Code (before or with new capture):** fix fallback PAD meta / fail-closed on Haar miss; optionally adopt softer Haar params after false-box check.
2. **Data:** re-collect Driver1 genuines (and ideally enroll) at consistent close frontal framing (match ~face_frac≥0.35, sharp, same camera mode). Replace the 17 Haar-miss genuines. Keep side/screen/blur attacks with detected faces for PAD.

Do not retrain yet. Do not change thresholds. After code+data, retrain per-driver PAD with `--exclude-fallback-crops` and re-measure live AUC on Haar-OK and full sets separately.

### Reproducibility

```bash
source .venv/bin/activate
set -a && source secrets.env && set +a
python scripts/diagnose_driver1_pad_haar.py
# → phases/driver1_pad_haar_diagnosis.json
```
