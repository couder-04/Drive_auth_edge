# DriveAuth Edge — roadmap (updated July 2026)

Supersedes `driveauth_edge_roadmap.md` for planning purposes; that file
stays as the historical baseline. This one reflects what's actually
shipped as of the July 2026 pipeline-fixes bundle
(`docs/pipeline-fixes-2026-07.md`), what's in flight, and what to do
next.

## Where things stand

| Phase | Status | Delta since last roadmap |
|---|---|---|
| 0. Architecture & software | ✅ done | +10 pipeline fixes shipped, 89 tests (was 50) |
| 1. Edge deployment (Thor) | ⏳ not started | unchanged |
| 2a. Off-the-shelf model swap-ins | 🟡 **1 of 6 components done** | risk head shipped |
| 2b. Fine-tuned models | ⏳ blocked on Phase 3 data | unchanged |
| 3. Dataset collection | 🟡 **1 of 6 modalities done** | 50k-row transaction set shipped |
| 4. Training | 🟡 **partial** | risk head trained (val AUC 0.9955) |
| 5. Testing & validation | 🟡 partial | 89 tests, overfit audit passes |
| 6. Benchmarking | ⏳ not started | unchanged |
| 7. GitHub & documentation | 🟡 partial | 3 new docs, still needs README polish |
| 8. Publications & demo | ⏳ not started | unchanged |

## What was actually shipped

### Phase 0 — pipeline fixes (July 2026 bundle)

All 10 findings from `docs/pipeline-review-2026-07.md` closed:

- ✅ **Fix #1** — trainer reads all 10 features (was: 4 hardcoded to zero)
- ✅ **Fix #2** — stratified train/val split with early stopping
- ✅ **Fix #3** — `driveauth/geo.py` + home-learning in `ProfileStore` +
  `_post_decision` wiring. `dist_from_home_km` and `in_trusted_zone` now
  have a real runtime producer.
- ✅ **Fix #4/#6** — per-driver `amount_z` at train time, matching how
  inference computes it from `ProfileStore.apply_to_context`.
- ✅ **Fix #5** — ONNX `label` output shape symbolic. No more batch-inference
  warnings.
- ✅ **Fix #7** — monotone (+1) constraints on all 10 GBT features.
- ✅ **Fix #8** — strict ONNX load + dynamic additive-fallback weights
  written by the trainer as a sidecar JSON.
- ✅ **Fix #9** — importance-aware `_reasons()`. Consistent with what the
  deployed model actually cares about.
- ✅ **Fix #10** — Brier score + reliability histogram on val set in
  `risk_gbt.json`.

Not addressed (intentionally, documented in `pipeline-fixes-2026-07.md`):
in-graph probability calibration; SHAP-per-prediction reasons; multi-modal
home clustering.

### Phase 2a — risk head (1 of 6 components)

- ✅ LightGBM trained end-to-end on 50k rows
- ✅ ONNX exported (`driveauth_store_phase2a/risk_gbt.onnx`)
- ✅ Val AUC **0.9955**, val_acc **0.9669**
- ✅ mean_risk_legit **0.053**, mean_risk_suspicious **0.944**
- ✅ Not overfit — 6-check audit passes (`scripts/overfit_audit.py`)
- ⏳ Voice, face, fingerprint, behavioral, trust-fusion — still mock

### Phase 3 — transaction dataset (1 of 6 modalities)

- ✅ 50k rows, 250 driver profiles, driver-conditional sampling
- ✅ 11 scenarios (5 legit, 6 suspicious), full schema
- ✅ 13 self-checking QA gates, reproducible with `--seed`
- ✅ Generator at `scripts/generate_risk_txns.py`
- ⏳ Voice, face, fingerprint, behavioral, OOD — not started

### Phase 5 — testing (partial)

- ✅ 89 unit + integration tests pass (was 50)
- ✅ Fail-closed paths verified for missing audio, missing face+voice,
  missing fingerprint, missing OOD stats, missing behavioral model
- ✅ Cache invalidation verified for tier upgrade, fraud state change,
  session expiry
- ✅ Overfit audit for the risk head (6 independent checks)
- ⏳ Timing side-channel test
- ⏳ OOD-drift attack simulation
- ⏳ Real-model failure mode extensions

## What to do next, priority-ordered

The single-action recommendation is at the top. Everything else is listed
in dependency order — later items sensibly wait for earlier ones.

### 🥇 One thing to do first

**Wire `driveauth/geo.py` into the Nova AI pipeline.** The trained risk
model already treats `dist_from_home` and `out_of_zone` as top-4 features
(gain-ranked). Without Nova passing GPS to
`DriveAuth.update_vehicle_context()`, those features stay at fail-neutral
defaults in production and offline AUC won't translate to live accuracy.
30-minute integration; largest value-per-hour ratio in the whole list.

```python
auth.update_vehicle_context(
    speed_kmh=vehicle.speed,
    ignition_on=vehicle.ignition,
    gps_lat=gps.lat,
    gps_lon=gps.lon,
    gps_accuracy_m=gps.hdop_estimate,
)
```

### Sprint 1 — no external dependencies (this week)

| Task | Effort | Blocks |
|---|---|---|
| Wire geo into Nova (above) | 30 min | nothing |
| Drop in pretrained ECAPA-TDNN (SpeechBrain `spkrec-ecapa-voxceleb`) as ONNX in `matchers/voice.py` | 0.5 day | 2b voice fine-tune |
| Timing side-channel test — measure `authenticate()` latency across accept/reject/step-up, KS-test they match `ESCALATION_CONSTANT_TIME_MS` | 0.5 day | Phase 6 security column |
| OOD-drift attack simulation against `ProfileStore.can_refresh_ood` | 0.5 day | Phase 6 security column |
| README + demo GIF polish | 1 day | Phase 7 launch |

### Sprint 2 — biometric enrollment protocols (weeks 2–4)

These start now because they have long lead times; getting them running
in parallel avoids blocking Phase 2b in a month.

| Task | Effort | Notes |
|---|---|---|
| Voice enrollment protocol design (device, prompt list, cabin/highway/tunnel/silent matrix) | 1 week | Phase 3 voice modality |
| First voice recording session | 1 week | Needs vehicle time |
| Face capture protocol (day/night/IR/sunglasses/mask/blur/side/replay) | 1 week | Needs RealSense or IR-capable camera |
| Fingerprint capture protocol (genuine/wrong/partial/wet/dry/spoof) | 1 week | Needs sensor SDK access |
| Behavioral / CAN log collection setup | 1 week | Needs vehicle-bus taps |

### Sprint 3 — real face + Thor (weeks 3–6)

| Task | Effort | Notes |
|---|---|---|
| Real face matcher: RealSense ID SDK OR InsightFace ArcFace ONNX + a PAD model, wired into the existing frame-suitability gate | 1 week | Phase 2a face component; the gate already exists |
| Fingerprint vendor SDK integration | 3–5 days | Phase 2a fingerprint component |
| Thor build + dependency install + GPU inference verified | 2 days | Phase 1 |
| Baseline hardware profile (CPU, GPU, RAM, latency per stage) | 1 day | Feeds Phase 6 |

Do Thor *after* at least one real biometric model is swapped in. Deploying
all-mocks on Thor tells you nothing about real inference cost.

### Sprint 4 — Phase 2b starts (weeks 4–8, gated on Sprint 2 data)

| Task | Trigger | Effort |
|---|---|---|
| Fine-tune ECAPA-TDNN on collected voice data | enrollment + genuine + replay classes collected | 3–5 days |
| Fine-tune ArcFace / retrain PAD on collected face data | enrollment + genuine + one attack class collected | 3–5 days |
| Behavioral model bake-off: LSTM vs GRU vs windowed-feature GBM | CAN logs collected | 1 week |
| Trust fusion: logistic regression on accept/reject labels | Phase 5 test-run labels collected | 3 days |

### Sprint 5 — testing + calibration (weeks 6–10)

| Task | Effort |
|---|---|
| Threshold re-baselining: rerun `scripts/calibrate_bio_thresholds.py` against real-model score distributions | 3 days |
| Real-model failure-mode tests (ONNX session mid-inference errors, camera driver timeout, sensor removal mid-transaction) | 1 week |
| Integration test suite covering full real-model pipeline | 1 week |

### Sprint 6 — benchmarking (weeks 10–14)

| Category | Metrics | Comparison baselines |
|---|---|---|
| Biometrics per modality | FAR, FRR, EER, ROC | isolated matcher vs. staged pipeline |
| PAD per modality | APCER, BPCER | isolated PAD vs. gated PAD |
| Risk head | Accuracy, precision, recall, F1, ROC-AUC | current head vs. heuristic baseline |
| Intent | Parsing accuracy, slot accuracy | current LLM vs. rule-based |
| Whole system | End-to-end latency (p50/p95/p99), throughput, CPU, GPU, RAM, power | staged pipeline vs. OTP-only vs. static-MFA vs. single-modality |

### Sprint 7 — documentation & publications (weeks 14–24)

**Documentation:**
- Public README rewrite with the fresh benchmark numbers
- Architecture diagrams (staged escalation, trust/risk separation, home
  learning)
- Demo GIF (5–10 seconds, payment step-up flow)
- Model documentation (what's trained on what, feature schemas, retrain
  cadence)
- Security assumptions document (threat model, mitigations, what's out
  of scope)
- LinkedIn technical post
- Medium/Substack deep-dive

**Publications (choose one lane; don't try both):**
- **Systems lane** — IEEE IV or ITSC. Frame around adaptive staged
  escalation as an automotive-systems contribution. Submission window
  late-Feb (IV) / late-Mar (ITSC); start writing 2 months earlier.
- **Security lane** — CCS or NDSS Workshop. Frame around the specific
  security analysis (timing side-channels, OOD-drift, escalation-policy
  security floor). Requires Sprint 1 timing/OOD work as evidence.

Ablation study material that's cheap to produce alongside benchmarks:
early-stop rate vs. security floor as a Pareto curve.

## Explicit non-goals (don't do these yet)

- **Retraining the risk head on real transactions.** Below ~5k real
  labelled transactions you're re-noising a good synthetic model. Wait.
- **Whole-pipeline latency optimisation.** Sprint 3's Thor profile tells
  you the actual bottleneck; anything before that is premature.
- **Paper writing before Sprint 6.** Nothing to compare against.
- **In-graph risk-score calibration.** Measured (Brier 0.026 on val); only
  fix it if real-data reliability histogram drifts far from the diagonal.
- **Multi-modal home clustering.** Single-centre Welford is fine until a
  real user complains about a two-homes scenario.
- **SHAP-per-prediction reasons.** Importance-aware filter is adequate;
  full per-call attribution requires keeping the LightGBM booster in
  memory at inference. Out of scope for now.

## Retrain / rebuild triggers

The risk head should be retrained when any of these happens:

- >5k new labelled real transactions collected (retrain, don't fine-tune)
- Overfit audit shows val_auc drop > 0.05 on real data vs. training-time
  val_auc
- `RiskContext` schema changes (new column added to the feature set)
- Policy thresholds change and you want the additive fallback recalibrated

The overfit audit (`scripts/overfit_audit.py`) is designed to be rerun on
real data any time — the six checks stay valid; only the absolute numbers
move.

## Success bar for each phase

| Phase | "Done" means |
|---|---|
| 1. Edge deployment | Thor runs end-to-end demo, hardware profile captured, p95 latency < policy budget |
| 2a. Off-the-shelf swap-ins | All 6 mock components replaced with pretrained real models, existing 89 tests still pass |
| 2b. Fine-tuned models | All 6 real models fine-tuned on collected data, per-modality FAR/FRR improve vs. 2a baseline |
| 3. Dataset collection | Enrollment + genuine + ≥1 attack class per modality; risk dataset from real transactions |
| 4. Training | All 6 models trained + ONNX-exported, overfit audits pass on each |
| 5. Testing | 150+ tests, timing side-channel test passes, OOD-drift simulation passes, real-model failure modes covered |
| 6. Benchmarking | Every row of the Sprint 6 table populated, ablation studies done, published as internal report |
| 7. Documentation | Public README + architecture doc + demo GIF + LinkedIn/Medium posts live |
| 8. Publications | Paper submitted to IV/ITSC OR CCS/NDSS; demo video published |

## Changelog

**July 2026** — this doc created. Roadmap refresh after the pipeline-fixes
bundle: Phase 2a risk head done, Phase 3 transaction modality done,
Phase 5 test count +39, Phase 6/7/8 unchanged. Structure switched from
phase-linear to sprint-oriented so priorities inside each phase are
explicit.
