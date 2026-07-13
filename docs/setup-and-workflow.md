# DriveAuth Edge — Fix-bundle setup & workflow

Two ways to get the updated repo on your machine, then a step-by-step
workflow: install → verify → train → validate → deploy.

## Option A — replace your working copy (fastest)

```bash
# From wherever you have Drive_auth_edge/ cloned:
mv Drive_auth_edge Drive_auth_edge.backup
tar -xzf Drive_auth_edge_fixed.tar.gz
mv Drive_auth_edge_fixed Drive_auth_edge
cd Drive_auth_edge
```

That's it. You're on the fixed branch.

## Option B — cherry-pick onto your branch

Use this if you have local uncommitted work you want to keep. The bundle
touches these files:

**Modified (7 files — replace in place):**

```
data/README.md
driveauth/api.py
driveauth/config.py
driveauth/policy.yaml
driveauth/profile_store.py
driveauth/risk_model.py
scripts/train_risk_gbt.py
```

**Added (7 files — copy in):**

```
docs/pipeline-fixes-2026-07.md
driveauth/geo.py
scripts/generate_risk_txns.py
scripts/overfit_audit.py
tests/test_geo.py
tests/test_profile_home.py
tests/test_risk_model_fallback.py
```

**Generated artefacts (not source — regenerate any time):**

```
data/driver1/transaction/txns.csv               # generate_risk_txns.py output
driveauth_store_phase2a/risk_gbt.onnx           # train_risk_gbt.py outputs
driveauth_store_phase2a/risk_gbt.json
driveauth_store_phase2a/risk_gbt_fallback_weights.json
```

## The tree, top-to-bottom

```
Drive_auth_edge/
├── README.md
├── DEMO.md
├── TODO.txt
├── driveauth_edge_roadmap.md
├── pyproject.toml
│
├── driveauth/                          # runtime library
│   ├── __init__.py
│   ├── api.py                          MODIFIED  home-learning wired into _post_decision
│   ├── audit_log.py
│   ├── config.py                       MODIFIED  +TRUSTED_ZONE_RADIUS_KM +HOME_LEARN_* +RISK_STRICT_LOAD
│   ├── decision_engine.py
│   ├── escalation.py
│   ├── fraud_state.py
│   ├── fusion.py
│   ├── geo.py                          NEW       Haversine + trusted-zone helpers
│   ├── intent.py
│   ├── ood_detector.py
│   ├── orchestrator.py
│   ├── policy.yaml                     MODIFIED  +geo.* section, +risk.strict_load, schema v2->v3
│   ├── policy_engine.py
│   ├── profile_store.py                MODIFIED  home_lat/lon fields, record_location, location_context, v3 migration
│   ├── quality_gate.py
│   ├── risk_model.py                   MODIFIED  strict-load, dynamic fallback weights, importance-aware reasons
│   ├── step_up_fallback.py
│   ├── step_up_otp.py
│   ├── template_store.py
│   ├── types.py
│   └── matchers/
│       ├── __init__.py
│       ├── base.py
│       ├── behavioral.py
│       ├── face.py
│       ├── finger.py
│       ├── mock.py
│       └── voice.py
│
├── scripts/
│   ├── calibrate_bio_thresholds.py
│   ├── demo_preflight.sh
│   ├── generate_risk_txns.py           NEW       50k-row dataset generator with QA gates
│   ├── overfit_audit.py                NEW       6-check overfit audit
│   ├── phase1b_thor_bench.py
│   ├── phase1b_thor_bootstrap.sh
│   ├── phase2a_demo.py
│   ├── phase2a_enroll.py
│   ├── phase2a_setup.py
│   └── train_risk_gbt.py               REWRITTEN full features, per-driver amount_z, train/val split, monotone, calibration, sidecars
│
├── tests/
│   ├── test_api.py
│   ├── test_core.py
│   ├── test_fixes.py
│   ├── test_geo.py                     NEW       12 tests for driveauth/geo.py
│   ├── test_production.py
│   ├── test_profile_home.py            NEW       15 tests for home-learning + v3 migration
│   └── test_risk_model_fallback.py     NEW       12 tests for strict-load + sidecars + reasons
│
├── docs/
│   ├── configuration.md
│   ├── integration.md
│   ├── pipeline-fixes-2026-07.md       NEW       full per-fix rationale + verification
│   └── review-fixes.md
│
├── architecture/
│   ├── overview.md
│   └── trust-risk-separation.md
│
├── data/
│   ├── README.md                       MODIFIED  full-schema example + driver_id
│   └── driver1/
│       ├── transaction/
│       │   └── txns.csv                GENERATED 50k-row synthetic dataset
│       ├── voice/enroll/…               (empty scaffolding, unchanged)
│       ├── face/enroll/…                (empty scaffolding, unchanged)
│       ├── finger/…                     (empty scaffolding, unchanged)
│       └── behavioral/                  (empty scaffolding, unchanged)
│
├── driveauth_store_phase2a/            # runtime state directory
│   ├── risk_gbt.onnx                   GENERATED trained model (val AUC 0.9955)
│   ├── risk_gbt.json                   GENERATED trainer meta + importances (feeds _reasons)
│   └── risk_gbt_fallback_weights.json  GENERATED additive-fallback weights (feeds RiskModel on ONNX-load-failure)
│
├── driveauth_store_pha/                # Phase 1b model store (unchanged)
│   ├── mobilefacenet.onnx
│   ├── mobilefacenet_int8.onnx
│   └── models/mobilefacenet.onnx
│
├── examples/
│   ├── basic_auth.py
│   └── payment_step_up.py              (still works unchanged — sanity-tested)
│
├── example_store/                       (audit log + OOD baselines, unchanged)
├── dashboard/                           (unchanged)
├── demo/                                (unchanged)
├── phases/                              (planning docs, unchanged)
└── dataset/data.ipynb                   (unchanged)
```

Legend: **NEW** = created by the fix bundle; **MODIFIED** = existing file
edited; **REWRITTEN** = fully replaced (existing file kept its name but
content is new); **GENERATED** = produced by running the scripts.

---

## Workflow: what to do now

### Step 1 — install dependencies (one time)

```bash
pip install lightgbm onnxmltools onnx skl2onnx onnxruntime scikit-learn pyyaml pytest
```

`--break-system-packages` if you're on Ubuntu / Debian with PEP 668.

### Step 2 — verify everything still works

```bash
cd Drive_auth_edge
python -m pytest tests/
```

Expected: **89 passed** (50 original + 39 new). If anything fails, you
have a local environment issue — do not proceed to training.

### Step 3 — sanity-check the example

```bash
PYTHONPATH=. python examples/payment_step_up.py
```

Expected last two lines:

```
High-value payment requires step-up: otp_mobile
Policy: driveauth-1.0:high_value_mandatory_stepup
```

### Step 4 — generate a training dataset (or use the shipped one)

The tarball ships a 50k-row `txns.csv` already generated with seed=42. If
you want your own draw or a different size:

```bash
python scripts/generate_risk_txns.py \
    --seed 42 --n 50000 \
    --out data/driver1/transaction/txns.csv \
    --meta meta.json
```

The generator runs 13 self-checking QA gates and exits non-zero if any
fail, so you can trust the file it produces. Passing gates on the seed=42
draw:

```
suspicious_rate                         0.280      OK
amount median ratio (susp/legit)        3.55       OK
behavioral_score mean diff              0.381      OK
quick logistic-regression val AUC       0.985      OK
… (see meta.json for the full report)
```

### Step 5 — train the risk head

```bash
python scripts/train_risk_gbt.py \
    --csv data/driver1/transaction/txns.csv \
    --out driveauth_store_phase2a/risk_gbt.onnx
```

Expected terminal output (approximately — LightGBM's exact tree depends
on your version):

```
Loaded 50000 rows · legit=36000 suspicious=14000
amount_mean_global=590.7 amount_std_global=766.2
optional cols present: {'dist_from_home_km': True, 'ignition_on': True, 'is_tunnel': True, 'behavioral_score': True}
per-driver stats: {'n_drivers_total': 250, 'n_drivers_with_per_driver_stats': 250, 'min_legit_per_driver': 5}

IN-MEMORY  train_auc=0.9957  val_auc=0.9955
           train_acc@0.5=0.9659  val_acc@0.5=0.9669
           mean_risk_legit(val)=0.053  mean_risk_suspicious(val)=0.944
           brier=0.0261

ONNX/val    {'onnx_acc@0.5': 0.9669, 'onnx_auc': 0.9955, ...}

Feature importances (gain):
  behavior_anomaly       570.0
  amount_z               434.0
  dist_from_home         396.0
  moving_fast            371.0
  ...
Wrote driveauth_store_phase2a/risk_gbt_fallback_weights.json
Wrote driveauth_store_phase2a/risk_gbt.onnx
Wrote driveauth_store_phase2a/risk_gbt.json
```

**Success criteria (from the original spec):**

| Metric | Target | Actual | Verdict |
|---|---|---|---|
| val AUC | ≥ 0.90 | 0.9955 | PASS |
| mean_risk_legit | ≲ 0.25 | 0.053 | PASS |
| mean_risk_suspicious | ≳ 0.70 | 0.944 | PASS |
| train_acc@0.5 | ≥ 0.85 | 0.966 | PASS |
| ONNX smoke inference (batch=1) | works | works | PASS |

### Step 6 — confirm the model isn't overfit

```bash
python scripts/overfit_audit.py
```

Runs six independent checks (train/val gap, 5-fold CV, leave-drivers-out,
cross-seed generalisation, shuffled-label baseline, feature ablation).
Expected: all six report `OK`. If any come back `SUSPECT`, the audit
prints the concrete number and the threshold it violated.

### Step 7 — commit

```bash
git add .
git status              # sanity-check what you're adding
git commit -m "risk head v2: full-feature trainer + geo producer + strict load"
```

### Step 8 — deploy / integrate

The ONNX and its two sidecars must live in the store directory that
`DriveAuth.load(store_dir=...)` reads. In the shipped repo that's
`driveauth_store_phase2a/`:

```
driveauth_store_phase2a/
├── risk_gbt.onnx                       required — the trained model
├── risk_gbt_fallback_weights.json      required — dynamic additive-fallback weights (fix #8)
└── risk_gbt.json                       optional — feeds importance-aware reasons (fix #9);
                                        without it, reasons fall back to threshold-only
```

If you're wiring into Nova AI's pipeline: **you must pass GPS into
`DriveAuth.update_vehicle_context()`** if you want the geo features to
actually work at runtime. The profile learns home online after
`HOME_LEARN_MIN_SAMPLES` (default 3) accepted authentications, so expect
a bootstrap period where `dist_from_home_km` stays fail-neutral. During
that window, other risk features carry the load — check `risk_gbt.json`
to see what your particular training run leaned on.

Example integration call:

```python
auth.update_vehicle_context(
    speed_kmh=vehicle.speed,
    ignition_on=vehicle.ignition,
    gps_lat=gps.lat,
    gps_lon=gps.lon,
    gps_accuracy_m=gps.hdop_estimate,
)
result = auth.authenticate(audio_np=…, amount=…, beneficiary=…, action="pay")
```

---

## Where things live at runtime

* **Trained model**            `driveauth_store_phase2a/risk_gbt.onnx`
* **Fallback weights**         `driveauth_store_phase2a/risk_gbt_fallback_weights.json`
* **Trainer meta / importances** `driveauth_store_phase2a/risk_gbt.json`
* **Per-driver profile**       `<store_dir>/<driver_id>.json` (holds home_lat/lon, amount Welford stats, etc.)
* **Audit log**                `<store_dir>/audit/driveauth_events.jsonl`
* **Policy overrides**         env vars (see `driveauth/policy.yaml` for the full list — every value has a `${DRIVEAUTH_*:default}` form)

## Rollback

If anything goes wrong in production:

```bash
# Turn off strict-load if a bad checkpoint blocks startup:
export DRIVEAUTH_RISK_STRICT_LOAD=0

# Delete the ONNX to force the additive-fallback path entirely:
rm driveauth_store_phase2a/risk_gbt.onnx
# (fallback still uses the sidecar weights if present, i.e. it still
# reflects what your trained model learned — just as a linear blend
# instead of a tree.)

# Revert to the backup you made in Option A:
rm -rf Drive_auth_edge && mv Drive_auth_edge.backup Drive_auth_edge
```

## Retraining cadence

Retrain the risk head when any of these happens:

* You collect > 5k new labelled real transactions (retrain, don't
  fine-tune — LightGBM doesn't fine-tune cleanly).
* Overfit audit shows drift on real data
  (val_auc drops > 0.05 vs. training-time val_auc).
* Feature schema changes (adding a new column to `RiskContext`).
* Policy thresholds change and you want the additive fallback recalibrated
  to match.

Each retrain rewrites all three files atomically (ONNX + `.json` +
`_fallback_weights.json`), so RiskModel.load picks up everything on next
process restart.
