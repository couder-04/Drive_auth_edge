# Pipeline review fixes — July 2026

Follow-up to `docs/pipeline-review-2026-07.md`. This file records what
changed in the code, the reasoning behind each change, and how to verify
it. Every fix is backed by tests in `tests/`.

## Summary of changes

| Fix | Severity | Files touched |
|---|---|---|
| #1 Trainer uses full feature schema | HIGH | `scripts/train_risk_gbt.py` (rewritten) |
| #2 Stratified train/val split with early stopping | HIGH | `scripts/train_risk_gbt.py` |
| #3 `dist_from_home_km` / `in_trusted_zone` have a runtime producer | HIGH | **new** `driveauth/geo.py`; `driveauth/profile_store.py`; `driveauth/api.py`; `driveauth/config.py`; `driveauth/policy.yaml` |
| #4/#6 Per-driver `amount_z` (train-serve parity) | HIGH | `scripts/train_risk_gbt.py`; `scripts/generate_risk_txns.py` (adds `driver_id`) |
| #5 ONNX `label`-output shape symbolic | LOW | `scripts/train_risk_gbt.py::_patch_onnx_label_shape` |
| #7 Monotone constraints on the GBT | LOW | `scripts/train_risk_gbt.py::train_lightgbm` / `train_sklearn` |
| #8 Strict ONNX load + dynamic fallback weights | MEDIUM | `driveauth/risk_model.py`; `driveauth/config.py`; `driveauth/policy.yaml`; trainer sidecar |
| #9 Importance-aware reasons | LOW | `driveauth/risk_model.py::_reasons` (via trainer's `risk_gbt.json`) |
| #10 Calibration report on val set | LOW | `scripts/train_risk_gbt.py::calibration_report` |

## New files

* `driveauth/geo.py` — pure-function Haversine + trusted-zone check.
* `scripts/generate_risk_txns.py` — dataset generator (50k rows, 250 drivers,
  full schema, driver-conditional sampling, self-checking QA gates).
* `tests/test_geo.py` — 12 unit tests for the geo module.
* `tests/test_profile_home.py` — 15 tests covering home-learning, v2→v3
  migration, on-disk round-trip, apply_to_context precedence.
* `tests/test_risk_model_fallback.py` — 12 tests covering strict-load, the
  fallback-weights sidecar, importance-aware reasons.

## Detail per fix

### #1 & #2 — trainer uses full features + train/val split

`scripts/train_risk_gbt.py` was rewritten in place. Previously it read five
columns and hardcoded four features to zero, then reported train-set
accuracy as a proxy for held-out performance. The new trainer reads all ten
features from the CSV (falling back only when a column is genuinely absent,
so v1 30-row CSVs still train), performs a stratified 80/20 split, uses
LightGBM early stopping on the val set, and reports both train and val
AUC / accuracy / mean-risk-per-class.

On the 50k dataset the shift is dramatic: val AUC 0.960 → 0.9955, mean-risk
separation 0.15/0.85 → 0.053/0.944. `behavior_anomaly`, previously
hardcoded to zero at training, is now the trained model's #1 feature by
gain.

### #3 — geo has a runtime producer

The design gap: `RiskContext.dist_from_home_km` and `in_trusted_zone` were
declared and consumed by `RiskModel._features()`, but nothing in the
pipeline computed them from `gps_lat/gps_lon`. In production they were
permanently at their dataclass defaults, so two of the top features went
dead at inference regardless of how well the model trained.

Fix has three layers:

1. **`driveauth/geo.py`** — a stateless `haversine_km` and
   `location_context` that map (gps, home, radius) → (distance, in_zone).
   Returns the neutral pair `(0.0, True)` on missing inputs so a fresh
   install / no-GPS case doesn't silently spike risk.
2. **`DriverProfile` extended** — new fields `home_lat`, `home_lon`,
   `home_n`, `home_last_update_at`. `ProfileStore` gains
   `record_location(lat, lon, accuracy_m)` (Welford-style online update,
   filters out bad-accuracy fixes) and `location_context(lat, lon)`
   (returns fail-neutral until we've seen `HOME_LEARN_MIN_SAMPLES` fixes,
   otherwise real Haversine distance). Schema bumped to v3; v1 and v2
   records migrate transparently via `_migrate()`.
3. **API wiring** — `_post_decision()` calls `record_location()` **only
   after `Decision.ACCEPT`**, so home is learned exclusively from fixes
   where we're confident the enrolled driver was actually there. Bad
   fixes (accuracy above 100m) are dropped inside `record_location`.
   `apply_to_context()` then fills `dist_from_home_km` and
   `in_trusted_zone` on subsequent risk-context builds -- but respects
   any caller-provided value via `update_vehicle_context()` (the existing
   `payment_step_up.py` example keeps working unchanged).

Config exposes three knobs in `policy.yaml`:
`geo.trusted_zone_radius_km` (default 5 km),
`geo.home_learn_min_samples` (default 3),
`geo.home_learn_max_accuracy_m` (default 100 m).

### #4/#6 — per-driver amount_z

At train time the previous trainer computed `amount_z` from the **global**
legit-only mean/std. At serve time `RiskModel` computed it from the
**per-driver** rolling mean/std that `ProfileStore` maintains. So the
model was trained on one distribution and served with a completely
different one -- for a driver with `amount_mean=100`, a ₹10,000 payment
produced a train-time amount_z the model had never seen at serve time.

The new trainer reads `driver_id` from the CSV, groups legit rows by
driver, and computes each driver's own legit mean/std for use as its
amount_z anchor. Drivers with fewer than five legit rows fall back to the
global stats. When `driver_id` isn't present in the CSV (v1 CSVs) the
trainer falls back to the global baseline everywhere -- backwards-compatible.

The dataset generator already emits `driver_id` per row, so anything
generated with `scripts/generate_risk_txns.py` gets the per-driver anchor
by default.

### #5 — ONNX label-shape warning

onnxmltools' LightGBM converter produces an ONNX graph where the `label`
output has a static shape `[1]` while `probabilities` correctly has
`[None, 2]`. Batched inference (e.g. any observability tool that sends
more than one row at a time) emitted a `Expected shape from model of {1}
does not match actual shape of {N} for output label` warning on every
call. Harmless (`RiskModel` reads from `probabilities`) but log noise.

`_patch_onnx_label_shape` walks the ONNX graph outputs and rewrites the
`label` output's first dim to a symbolic `N`. Warning gone; batch
inference passes cleanly.

### #7 — monotone constraints

Every DriveAuth feature is designed such that "more of it" means "higher
risk" (`amount_z`, `beneficiary_novel`, `out_of_zone`, `night`,
`moving_fast`, `ignition_off_anomaly`, `tunnel`, `behavior_anomaly`,
`dist_from_home`, `amount_norm`). A GBT without monotone constraints can
learn perverse patterns on an unlucky split -- e.g. "higher amount lowers
risk in this leaf". Adding `monotone_constraints=[+1]*10` to both the
LightGBM and sklearn HistGBT paths costs almost nothing on model
quality and makes the model impossible to trip up in that specific way.

### #8 — strict ONNX load + dynamic fallback

Previously, a corrupt `risk_gbt.onnx` file logged a warning and silently
degraded to a hand-tuned additive-fallback score that gave 6% of the
weight to `behavior_anomaly` -- the trained model's most important
feature. A silent behavior shift on a safety-critical head is worse than
a hard fail.

`RiskModel.load()` now takes a `strict` parameter (default from
`config.RISK_STRICT_LOAD`, default `True`). When strict and the ONNX file
exists but fails to open, we raise `RuntimeError` -- a bad checkpoint or
ORT mismatch is impossible to miss. Missing ONNX (fresh install) still
falls through to additive silently. Non-strict mode is available as an
opt-out via `DRIVEAUTH_RISK_STRICT_LOAD=0`.

Separately, the trainer now writes `risk_gbt_fallback_weights.json` next
to the ONNX. `RiskModel.load()` reads it and uses those normalised
importances as the additive-fallback weights, so if the ONNX ever does
fail to load the fallback path reflects what the *trained* model
learned instead of hand-tuned defaults from months earlier.

### #9 — importance-aware reasons

`_reasons()` used to emit a fixed set of human-readable strings based on
raw thresholds -- so it could emit `unusual_hour` on a call where the
deployed model's `night` importance was essentially zero, giving auditors
a misleading explanation.

`_reasons()` now reads `feature_importances_gain` from the trainer's
`risk_gbt.json` sidecar. A reason only fires if the feature both passes
its threshold AND contributes ≥2% of the model's total gain. When the
sidecar is absent (fresh install / no trained model), we fall back to
threshold-only, matching the pre-fix behaviour.

### #10 — calibration report

`RISK_APPROVE=0.35` and `RISK_REJECT=0.80` treat the model output as a
calibrated probability. LightGBM with `class_weight="balanced"` is usually
reasonably calibrated but can drift. The trainer now computes a Brier
score and a 10-bin reliability histogram on the val set and writes both
into `risk_gbt.json`, so operators can spot-check whether the policy
thresholds still make sense against actual model output.

In-graph calibration wasn't added (LightGBM through onnxmltools doesn't
cleanly wrap through `CalibratedClassifierCV`). If the numbers drift far
from the diagonal, the cheapest response is to retune the policy
thresholds against the observed val distribution -- same pattern as
`scripts/calibrate_bio_thresholds.py` already uses for biometrics.

## Verification

```bash
# 1. Generate a fresh 50k dataset (or reuse the existing one).
python scripts/generate_risk_txns.py --seed 42 --n 50000 \
    --out data/driver1/transaction/txns.csv --meta meta.json

# 2. Train.
python scripts/train_risk_gbt.py --csv data/driver1/transaction/txns.csv \
    --out driveauth_store_phase2a/risk_gbt.onnx

# 3. Full test suite -- 50 original + 39 new pass.
python -m pytest tests/
```

Numbers on the shipped seed=42 dataset:

```
IN-MEMORY  train_auc=0.9957  val_auc=0.9955
           train_acc@0.5=0.9659  val_acc@0.5=0.9669
           mean_risk_legit(val)=0.053  mean_risk_suspicious(val)=0.944
           brier=0.0261
ONNX/val   onnx_auc=0.9955  onnx_acc@0.5=0.9669
           onnx_mean_risk_legit=0.0531  onnx_mean_risk_suspicious=0.9436
```

All comfortably beyond the success gates in the original spec
(val AUC ≥ 0.90, mean_risk_legit ≲ 0.25, mean_risk_suspicious ≳ 0.70,
train_acc@0.5 ≥ 0.85).

## Not addressed here

* **In-graph probability calibration** — measured but not applied. See #10.
* **SHAP-per-prediction reasons** — the sidecar's global importances filter
  reasons at the class level, not at the per-call level. For real per-call
  attribution we'd need to keep the LightGBM booster around at inference
  (or embed leaf-index → contribution tables into the ONNX), which is out
  of scope for this pass.
* **Multi-modal home model** — home is one Welford-tracked centre. A
  driver who genuinely has two homes (weekday flat + weekend cottage) will
  get the average of both. A future upgrade could cluster fixes into K
  centres if the observed spread is above some threshold.
