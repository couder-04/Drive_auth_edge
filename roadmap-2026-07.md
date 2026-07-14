# DriveAuth Edge — roadmap (updated July 2026)

Supersedes `driveauth_edge_roadmap.md` for planning purposes; that file
stays as the historical baseline. This one reflects what's actually
shipped as of mid-July 2026 (pipeline-fixes bundle + Phase 3 capture +
Phase 2a enroll + dashboard Nova contract), what's deferred, and what
to do next.

## Where things stand

| Phase | Status | Delta since last roadmap |
|---|---|---|
| 0. Architecture & software | ✅ done | +10 pipeline fixes; geo API live; dashboard Nova I/O contract |
| 1. Edge deployment (Thor) | ✅ **done** | Mac 1a + Thor 1b mock; p95 ≤ 10 ms; see `phases/phase1.md` |
| 2a. Off-the-shelf model swap-ins | 🟡 **3 of 6** | risk ✅ · voice ECAPA enrolled ✅ · face MobileFaceNet enrolled ✅ · finger / behavioral / trust-fusion still mock |
| 2b. Fine-tuned models | ⏳ gated | voice+face data exists; prefer same-person face before fine-tune |
| 3. Dataset collection | 🟡 **synth/min sets done** | txns 50k ✅ · voice ✅ · face (RDJ) ✅ · finger/beh/ood synth ✅ · real HW + own-face pending |
| 4. Training | 🟡 partial | risk head trained (val AUC 0.9955); bio thresholds calibrated (not applied) |
| 5. Testing & validation | 🟡 partial | ~98 tests; overfit audit; score_provider; timing + OOD-drift ✅ |
| 6. Benchmarking | ⏳ not started | unchanged |
| 7. GitHub & documentation | 🟡 partial | README + demo GIF ✅; security assumptions / posts open |
| 8. Publications & demo | ⏳ not started | unchanged |

## What was actually shipped

### Phase 0 — pipeline fixes (July 2026 bundle)

All 10 findings from `docs/pipeline-review-2026-07.md` closed (see
`docs/pipeline-fixes-2026-07.md`). Geo helpers + home learning are in
code; **Nova live GPS wiring is deferred** — dashboard / demos set context
manually until telematics is integrated.

### Phase 2a — models (3 of 6)

| Component | Status |
|---|---|
| Risk LightGBM → `risk_gbt.onnx` | ✅ val AUC 0.9955, overfit audit passes |
| Voice ECAPA-TDNN (SpeechBrain) | ✅ pretrained loaded; enrolled from `data/driver1/voice` |
| Face MobileFaceNet ONNX | ✅ pretrained loaded; enrolled from RDJ face set |
| Finger | ⏳ mock + `ManualScores` until sensor SDK |
| Behavioral | ⏳ mock + CAN synth CSVs until recorder |
| Trust fusion | ⏳ static weights (logreg is Phase 2b/4) |

Enrollment / demo:

- `scripts/phase2a_setup.py` · `phase2a_enroll.py` · `phase2a_demo.py`
- Staged escalation verified: genuine voice → early-stop ACCEPT; attack
  voice → probes face → STEP_UP when fused trust ambiguous
- Finger/behavioral stand-in: `driveauth/matchers/score_provider.py` +
  `scripts/phase3_synth_demo.py` + `DRIVEAUTH_MANUAL_SCORES`

### Phase 3 — datasets

| Modality | Status | Location / notes |
|---|---|---|
| Transaction | ✅ 50k rows | `data/driver1/transaction/txns.csv` |
| Voice | ✅ enroll 8 / genuine 20 / noisy 5 / attacks | silent, replay, other_speaker |
| Face | ✅ enroll 8 / genuine 20 / blur·side·screen | RDJ Kaggle — **replace with own face** before 2b |
| Finger | ✅ synth ridge PNGs | `scripts/generate_phase3_synth.py` — replace with sensor |
| Behavioral | ✅ synth CAN windows | 20 genuine + 6 attack CSVs |
| OOD negatives | ✅ face/voice/finger | dataset for future OOD work; live gating still `ood_stats/*.npz` |

Calibration snapshot: `phases/phase2b_calibration.json` (voice separates
well; face attacks overlap genuine — **do not lower** `policy.yaml`
accept bars until own-face re-enroll).

### Dashboard & Nova contract

- Dashboard: 3 columns — **Transaction** · **Manual stand-ins (auto later)**
  · **Result + Nova ↔ DriveAuth I/O contract**
- Manual column covers biometric scores, GPS, speed/ignition/tunnel
- Contract also documented in `docs/integration.md`

### Phase 5 — testing (partial)

- ✅ Unit/integration suite (~98) including fail-closed + cache invalidation
- ✅ Overfit audit for risk head
- ✅ `tests/test_score_provider.py`
- ✅ Timing side-channel test (`tests/test_security_sprint1.py`)
- ✅ OOD-drift attack simulation (`tests/test_security_sprint1.py`)
- ⏳ Real-model failure-mode extensions

### Phase 1 — Edge (complete)

Mac 1a + Thor 1b mock pipeline shipped and measured:

- Profiles: `phases/mac.txt` · `phases/thor.txt`
- Record: `phases/phase1.md` (budget **MOCK_AUTH_P95_MS = 10** → Thor p95 **0.9 ms** PASS)
- Re-run: `scripts/phase1b_thor_bootstrap.sh` · `phase1b_thor_bench.py`

Optional later: Phase 2a ECAPA/face latency on Thor GPU EP (not required for Phase 1).

## What to do next, priority-ordered

### 🥇 Do first (this week)

1. **Replace RDJ face enroll/genuine with your own face** (match voice
   identity) → re-run `phase2a_enroll.py` → `calibrate_bio_thresholds.py`
2. Keep thresholds conservative until face attack overlap improves

### Deferred to Nova integration (not blocking Mac work)

**Wire GPS in Nova** when the pipeline is connected — same API already
exists:

```python
auth.update_vehicle_context(
    speed_kmh=vehicle.speed,
    ignition_on=vehicle.ignition,
    gps_lat=gps.lat,
    gps_lon=gps.lon,
    gps_accuracy_m=gps.hdop_estimate,
)
```

Until then: set GPS / dist / zone / speed in the dashboard **Manual
stand-ins** column.

### Sprint 1 — Mac / software (this week)

| Task | Effort | Notes |
|---|---|---|
| Own-face capture + re-enroll + calibrate | 0.5–1 day | Unblocks honest 2b |
| Timing side-channel test | 0.5 day | `ESCALATION_CONSTANT_TIME_MS` |
| OOD-drift attack simulation | 0.5 day | `ProfileStore.can_refresh_ood` |
| README + demo GIF polish | 1 day | Phase 7 |

### When hardware arrives (days–weeks)

Finger sensor · face cam · CAN recorder expected soon.

| Task | Notes |
|---|---|
| Replace synth finger / CAN / OOD with real captures | Keep folder schema |
| Finger SDK + CAN → modules emitting `ModalityResult(score∈[0,1])` | Drop-in for `ManualScores` |
| Nova: call `update_vehicle_context` from telematics thread | Before each payment auth |

### Sprint 3 — Thor ✅ done (mock + Phase 2a CUDA)

Phase 1 closed — see `phases/phase1.md`.

Phase 2a real-model latency:

- ✅ Mac: `phases/phase2a-mac.txt` (ECAPA CPU · face CoreML)
- ✅ Thor: `phases/phase2a-thor.txt` (ECAPA cuda · face CUDA EP via SM110 ORT build;
  micro p95 7.7 ms · high-value p95 9.2 ms)
### Sprint 4–8

Unchanged intent: Phase 2b fine-tunes → re-baseline thresholds →
benchmarks → docs → paper. See tables below; triggers stay the same.

#### Sprint 4 — Phase 2b (gated on clean same-person data)

| Task | Trigger |
|---|---|
| Fine-tune ECAPA on voice | enroll + genuine + replay present ✅ |
| Fine-tune face / PAD | **own-face** enroll + genuine + attack |
| Behavioral bake-off | real CAN (synth is stand-in only) |
| Trust fusion logreg | labeled auth outcomes |

#### Sprint 5 — testing + calibration

Threshold re-baselining on real-model distributions; real-model failure
modes; fuller integration suite. Target 150+ tests.

#### Sprint 6 — benchmarking

FAR/FRR/EER, PAD, risk metrics, latency; vs OTP-only / static MFA /
single-modality / staged pipeline.

#### Sprint 7–8 — docs & publications

README rewrite, demo GIF, LinkedIn/Medium; IV/ITSC **or** CCS/NDSS once
Sprint 1 timing/OOD evidence exists.

## Explicit non-goals (don't do these yet)

- Retraining the risk head on real txns (wait for ~5k labelled)
- Applying `phases/phase2b_suggested.env` as default (weakens ACCEPT bar
  while face attack overlap is high)
- Whole-pipeline latency optimisation before Phase 2a Thor (real model) profile
- Paper writing before Sprint 6
- In-graph risk calibration / multi-modal home clustering / SHAP-per-call
- FingerNet / behavioral LSTM training before real HW data

## Retrain / rebuild triggers

Risk head — retrain when:

- >5k new labelled real transactions
- Overfit audit shows val_auc drop > 0.05 on real data vs train-time
- `RiskContext` schema changes
- Policy thresholds change and additive fallback needs recalibration

Bio matchers — re-enroll / recalibrate when face or voice enrollment
identity changes (e.g. RDJ → self).

## Success bar for each phase

| Phase | "Done" means |
|---|---|
| 1. Edge deployment | ✅ Thor runs end-to-end demo, hardware profile captured, mock p95 &lt; 10 ms |
| 2a. Off-the-shelf swap-ins | All 6 mock components replaced with pretrained/real modules; tests still pass |
| 2b. Fine-tuned models | Domain fine-tunes improve FAR/FRR vs 2a baseline |
| 3. Dataset collection | Same-person enroll+genuine+≥1 attack per modality; HW replaces synth where possible |
| 4. Training | Models ONNX-exported; overfit audits pass |
| 5. Testing | 150+ tests; timing + OOD-drift + real-model failures covered |
| 6. Benchmarking | Sprint 6 table populated + ablations |
| 7. Documentation | Public README + contract docs + demo GIF + posts |
| 8. Publications | Paper submitted; demo video published |

## Changelog

**July 2026 (mid+)** — Phase 1 closed: Mac 1a + Thor 1b mock profiles,
`phases/phase1.md` latency budget (p95 ≤ 10 ms), checklist restored in
`phases/thor.md`; README/TODO/roadmap marked Phase 1 done.

**July 2026 (mid)** — Phase 3 voice/face/synth finger·beh·ood filled;
Phase 2a voice+face enrolled; OOD 128↔512 mock fix; bio calibrate
artifact; `score_provider` + phase3 demo; dashboard Manual stand-ins +
Nova I/O contract; GPS-to-Nova deferred to integration (manual for now).

**July 2026** — doc created after pipeline-fixes bundle: Phase 2a risk
head done, Phase 3 transaction modality done, Phase 5 test count +39.
Structure switched from phase-linear to sprint-oriented.
