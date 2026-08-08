# Fairness validation protocol

DriveAuth Edge does **not** claim demographic parity until this study is
completed on consented field data. Current code provides:

- Face quality gates (brightness, sharpness, two-eye detection)
- Audit score bucketing (`trust_bucket`, `risk_bucket`) — telemetry only
- Proxy analysis script: `scripts/analyze_fairness.py` (lighting bins)

## Study goals

1. Measure false reject rate (FRR) stratified by **lighting condition** and
   **skin tone** (Fitzpatrick I–VI or Monk scale — label protocol TBD with IRB/counsel).
2. Measure quality-gate rejection rates before model scoring (capture UX burden).
3. Document any statistically significant gaps and mitigation (lighting normalize,
   capture guidance, threshold review).

## Required dataset

- ≥30 drivers per stratum (target; adjust with statistician)
- Controlled lighting: dark cabin, daylight, overhead LED, side sun
- Consented still captures + short voice clips per condition
- Metadata: `lighting_bin`, `skin_tone_label`, `device_id`, `timestamp`

## Procedure

1. Enroll drivers via `/register` (minimal-capture policy).
2. Capture verification attempts per lighting condition (3+ per driver).
3. Run `scripts/analyze_fairness.py` for lighting-proxy pre-check.
4. Export audit buckets + modality outcomes (no raw biometrics off-device).
5. Compute FAR/FRR per stratum; compare to global baseline.
6. File results in `phases/fairness_report.md` (create when study runs).

## Non-claims until complete

Do not claim fairness, demographic parity, or regulatory compliance in marketing
or IEEE submission until rows exist in `phases/fairness_report.md`.
