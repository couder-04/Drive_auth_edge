# DriveAuth Edge — full revised roadmap

**Verified, not assumed:** Phase 0's checklist was checked directly against `staged_driveauth-edge.zip` rather than taken on faith. `ruff check driveauth/` passes clean. There are 50 tests across four files, and `test_production.py` specifically already covers fail-closed behavior (missing audio, missing face+voice, missing fingerprint, missing OOD stats, missing behavioral model), cache invalidation (tier upgrade, fraud-state change, session expiry), and real-value threading (risk model receiving actual transaction amounts, tier classification using real beneficiary data) — this is stronger production-hardening coverage than a first read of the checklist suggests, and it changes a couple of the revisions below.

Every revision from the previous pass is kept and one is corrected in light of the `test_production.py` findings, flagged **⚠ revised**.

---

## Phase 0 — Current status ✅ (confirmed by inspection)

| Item | Status |
|---|---|
| Overall architecture | ✅ |
| Adaptive authentication (staged escalation) | ✅ |
| Escalation policy | ✅ |
| Trust / Risk / Confidence separation | ✅ |
| Policy engine | ✅ |
| Fraud state machine (incl. bootstrap) | ✅ |
| Enrollment pipeline | ✅ |
| Driver profile manager | ✅ |
| Session / decision cache | ✅ |
| Audit logging | ✅ |
| OTP / PIN fallback | ✅ |
| OOD integration | ✅ |
| Implementation, API, unit + integration tests | ✅ (50 tests) |
| Production hardening | ✅ (fail-closed paths + cache invalidation confirmed tested, not just implemented) |
| Ruff clean | ✅ (verified) |
| Demo works | ✅ |

**Current models:** ASR ✅, LLM ✅. Voice/face/finger matchers = mock, risk = heuristic, trust fusion = static, behavioral = mock. This is the honest starting line for Phase 2 — everything above is real engineering; everything below this line is model work.

---

## Phase 1 — Edge deployment
**Priority: ⭐⭐⭐⭐⭐ — in progress**

Goal: run the full pipeline on real hardware **before** swapping models, so every later model change has a measured baseline to compare against. Mocks are intentional in this phase.

### Phase 1a — Mac workstation baseline ✅

Done on developer hardware while Thor is unavailable. Record: [`phases/mac.txt`](phases/mac.txt).

| Item | Status | Notes |
|---|---|---|
| Pipeline boots (`pytest`, demo) | ✅ | 50 tests; mock matchers |
| Auth latency profile | ✅ | n=50 · p50=0.7ms · p95=0.8ms · max=9.6ms |
| RSS / memory | ✅ | ≈28.2 MB (pid snapshot) |
| Device inventory | ✅ | MacBook Air M4 · 16 GB · Python 3.11.14 · macOS 26.3.1 |
| `DRIVEAUTH_USE_MOCK=1` | ✅ | Phase 1 policy — no real models yet |

**Mac baseline (2026-07-10):**

```text
Device: MacBook Air (Mac16,13) — Apple M4, 10-core (4P+6E), 16 GB
OS: macOS 26.3.1 (25D2128)
Python: 3.11.14
DRIVEAUTH_USE_MOCK=1
Auth latency: n=50  p50=0.7ms  p95=0.8ms  max=9.6ms
RSS: 28912 KB ≈ 28.2 MB
```

Use these numbers as the **comparison anchor** when Thor comes online (same bench, same mock flag).

### Phase 1b — NVIDIA Thor ⬜ next

Blocked on board availability. When Thor is up:

| Step | Action | Pass criteria |
|---|---|---|
| 1 | Flash/boot BSP · SSH · disk | Shell access stable |
| 2 | `pip install -e ".[dev,dashboard,onnx]"` | Import `driveauth` succeeds |
| 3 | `pytest` · `driveauth-demo` · dashboard on `0.0.0.0:8765` | ACCEPT micro path works; audit log grows |
| 4 | Confirm ORT providers (`CPU` now; `CUDA`/`TensorRT` when ready) | Providers printed at startup |
| 5 | Same latency bench as Mac + `jtop`/`nvidia-smi` | Write `phases/thor.txt` |
| 6 | Optional: 30 min soak (dashboard idle + periodic auth) | No crash; RSS stable |

Env on Thor (Phase 1):

```bash
export DRIVEAUTH_STORE_DIR=/var/lib/driveauth/store
export DRIVEAUTH_USE_MOCK=1
export DRIVEAUTH_FINGERPRINT_AVAILABLE=0
export DRIVEAUTH_DASHBOARD_HOST=0.0.0.0
export DRIVEAUTH_DASHBOARD_PORT=8765
```

Latency bench (identical to Mac):

```bash
python3.11 - <<'PY'
import time, tempfile, os
from driveauth import DriveAuth
from testsupport import good_audio, mature

print("pid", os.getpid())
auth = DriveAuth.load(tempfile.mkdtemp(), use_mock_matchers=True)
mature(auth)
audio = good_audio()
times = []
for _ in range(50):
    t0 = time.perf_counter()
    auth.authenticate(audio_np=audio, amount=50, beneficiary_known=True, beneficiary="Mom")
    times.append((time.perf_counter() - t0) * 1000)
times.sort()
print(f"n=50  p50={times[24]:.1f}ms  p95={times[47]:.1f}ms  max={times[-1]:.1f}ms")
PY
```

### Deliverable

| Artifact | Status |
|---|---|
| `phases/mac.txt` — Mac hardware profile | ✅ |
| `phases/thor.txt` — Thor hardware profile | ⬜ |
| DriveAuth running on Thor (mock pipeline) | ⬜ |
| GPU/NPU stack verified (providers listed) | ⬜ |

**Phase 1 complete when:** Thor profile exists and mock pipeline + dashboard are verified on-device. Then start Phase 2a (pretrained model swap), not before.

**Out of scope for Phase 1:** ECAPA / ArcFace / fingerprint SDK / real IR-CAN wiring (Phase 2+).

---

## Phase 2 — Replace mock models
**Priority: ⭐⭐⭐⭐⭐ — 2a in progress on Mac**

> **⚠ revised — interleave with Phase 3, don't sequence after it.** ECAPA-TDNN anti-spoof, ArcFace/PAD, and LightGBM risk all need real data to train or fine-tune. Split this phase in two:
> - **2a (can start immediately, no data dependency):** swap in off-the-shelf pretrained checkpoints so the real pipeline runs end-to-end on real models, even undertrained for this domain.
> - **2b (gated on Phase 3 minimums):** fine-tune/retrain each model once its Phase 3 dataset has at least enrollment + genuine + one attack class. Don't let "mock models replaced" quietly collapse 2a and 2b into one claim.

### Phase 2a — pretrained on Mac (checklist)

See [`phases/phase2a.md`](phases/phase2a.md).

```bash
pip install -e ".[voice,face,onnx,dev]"
python scripts/phase2a_setup.py --store ./driveauth_store_phase2a
python scripts/phase2a_enroll.py --store ./driveauth_store_phase2a --synthetic
python scripts/phase2a_demo.py --store ./driveauth_store_phase2a
python scripts/phase2a_demo.py --store ./driveauth_store_phase2a --bench 20
```

| Piece | 2a status |
|---|---|
| Voice ECAPA-TDNN (SpeechBrain) | wired + setup script |
| Face ArcFace-MobileFaceNet ONNX | wired + setup script |
| Finger / behavioral | stay mock until HW/weights |
| Hybrid `DriveAuth.load(use_mock_matchers=False)` | falls back per-modality |
| Risk / trust fusion | still heuristic / static (2b/4) |

**Voice** — ECAPA-TDNN, voice anti-spoof, enrollment pipeline.

**Face** — RealSense ID / ArcFace, PAD model, IR integration, verification-quality crop (the frame-suitability gate from the architecture review already exists in code — wire the real face detector into it rather than replacing it).

**Fingerprint** — vendor SDK, enrollment, liveness (if the sensor supports it).

**Behavioral** — LSTM, CAN interface. *Worth a bake-off against a lighter GRU or windowed-feature GBM given the edge power budget — not because LSTM is expensive, but because it's the one Phase 2 model without an obvious "boring and interpretable wins" argument the way risk/trust fusion have.*

**Risk** — replace the heuristic with LightGBM or XGBoost.

**Trust fusion** — replace the weighted average with logistic regression or a small MLP.

*(These two choices are correct and don't need revision: tabular/structured data, need for feature attribution during disputes, and a GBM/logreg beats a deep model here on both accuracy and auditability.)*

---

## Phase 3 — Dataset collection
**Priority: ⭐⭐⭐⭐⭐**

> **⚠ revised — start in parallel with Phase 1, not after Phase 2.** Enrollment + genuine + one basic attack class per modality is the Phase 2b gate; the sooner this starts, the sooner 2b can begin.

| Modality | Collect |
|---|---|
| Voice | Enrollment, genuine, replay, synthetic voice, noisy cabin, highway, tunnel, silent audio |
| Face | Day, night, IR, sunglasses, mask, blur, side pose, replay attack |
| Fingerprint | Genuine, wrong finger, partial, wet, dry, spoof |
| Behavioral | CAN/IMU — steering angle+rate, throttle, brake pedal, long/lat accel, yaw, speed |
| Transaction | Amount, beneficiary, time, GPS, fraud labels |
| OOD | Unknown speakers, unknown faces, unknown fingerprints, strange lighting, audio attacks |

---

## Phase 4 — Training
**Priority: ⭐⭐⭐⭐**

**Risk model** — transaction history → LightGBM. Feature engineering → train → tune → export ONNX.

**Trust fusion** — authentication outcomes → logistic regression. Collect labels → train → evaluate → export ONNX.

**Behavioral model** — CAN telemetry → LSTM (or the lighter alternative from Phase 2). Sequence preprocessing → train → quantize → export ONNX.

**OOD (optional)** — embeddings → autoencoder.

---

## Phase 5 — Testing
**Priority: ⭐⭐⭐⭐⭐**

**Unit** — 100+ tests (currently 50; the realistic gap is tests for the *new model-backed* matchers, which don't exist yet because the models don't exist yet — not a gap in the current mock-based suite, which is already solid).

**Integration** — full end-to-end pipeline.

**Security**
- Replay attacks, face replay, deepfake voice, sensor removal, cache bypass, OTP bypass
- **⚠ add:** timing side-channel testing against `ESCALATION_CONSTANT_TIME_MS` — mitigation exists in code, unvalidated adversarially
- **⚠ add:** OOD-baseline drift attack simulation against `ProfileStore.can_refresh_ood` — same situation

**Robustness** — low light, noise, missing sensors, corrupted data, OOD.
> **⚠ revised — lighter than originally flagged.** `test_production.py` already covers missing-audio, missing-face-with-no-voice, missing-fingerprint, missing-OOD-stats, and missing-behavioral-model as explicit fail-closed tests. This phase's robustness work is mostly *extending* that coverage to real-model failure modes (a real ONNX session throwing mid-inference, a real camera driver timing out) rather than building fail-closed behavior from scratch.

**Hardware** — Thor, Jetson, RK3588 (optional).

**⚠ add — regression re-baselining.** Once real models replace mocks, thresholds calibrated against mock score distributions (e.g. "single-modality accept at 0.8 confidence") need re-validation against real-model distributions. Explicit line item so it isn't silently folded into "Integration" and skipped.

---

## Phase 6 — Benchmarking
**Priority: ⭐⭐⭐⭐** · **Status: ✅ Done (2026-07-15)** — see `phases/phase6.md`

| Category | Metrics |
|---|---|
| Biometrics | FAR, FRR, EER, ROC |
| PAD | APCER, BPCER |
| Risk | Accuracy, precision, recall, F1, ROC-AUC |
| Intent | Parsing accuracy, slot accuracy |
| Whole system | End-to-end latency, throughput, CPU, GPU, memory, power |

**Compare against:** OTP-only, face-only, voice-only, finger-only, static MFA, and the adaptive staged pipeline itself — the right set; it's what turns "staged escalation" from an architectural claim into an empirical result.

**Artifacts:** `scripts/phase6_benchmark.py` → `phases/phase6_sprint6.json` + `phases/phase6.md`.

---

## Phase 7 — Documentation & open source
**Priority: ⭐⭐⭐⭐**

**GitHub repository** — clean folder structure, README, architecture diagrams, installation guide, demo GIF, API docs, config docs, model documentation, security assumptions, dataset format, license, contributing guide, issues & roadmap, release v1.0.

**LinkedIn technical post** — problem, why existing MFA is insufficient in vehicles, architecture overview, adaptive authentication, demo screenshots, GitHub link, key engineering learnings.

**Medium / Substack** — *"Building DriveAuth Edge: An Offline AI-Powered Authentication System for In-Car Payments."* Sections: motivation, architecture, ML pipeline, security design, edge deployment, testing, lessons learned.

---

## Phase 8 — Research
**Priority: ⭐⭐⭐⭐**

**White paper** (~15–20 pages) — abstract, introduction, related work, architecture, models, security, testing, results, future work.

**Conference paper** — venue shortlist, prioritized:
- **IEEE IV, IEEE ITSC** — best fit; automotive-systems venues matching the actual contribution.
- **ACM CCS, NDSS Workshop** — only if the paper leads with the security analysis (timing side-channels, OOD-drift attacks, the staged-escalation security floor) rather than the systems architecture. Decide this framing before writing.
- **IEEE ICC, IEEE Globecom, ACM SenSys, ACM MobiSys** — deprioritize unless the CAN/telematics networking angle becomes the paper's actual novel contribution.

Add: experimental evaluation, benchmarks, comparisons, ablation studies (early-stop rate vs. security floor is a natural ablation given the escalation policy's design).

**Demo video** (5–8 min) — problem statement, architecture animation, live demo, dashboard, Thor deployment, authentication flow, security scenarios, performance metrics.

---

## Overall roadmap

| Phase | Status | Priority |
|---|---|---|
| 0. Architecture & software | ✅ Done (verified) | — |
| 1. Edge deployment | ⏳ Next | ⭐⭐⭐⭐⭐ |
| 2. Replace mock models (2a off-the-shelf → 2b fine-tuned) | ⏳ | ⭐⭐⭐⭐⭐ |
| 3. Dataset collection (parallel with Phase 1) | ⏳ | ⭐⭐⭐⭐⭐ |
| 4. Train DriveAuth-specific models | ⏳ | ⭐⭐⭐⭐ |
| 5. Testing & validation (+ timing/OOD-drift + re-baselining) | ⏳ | ⭐⭐⭐⭐⭐ |
| 6. Benchmarking | ⏳ | ⭐⭐⭐⭐ |
| 7. GitHub & technical documentation | ⏳ | ⭐⭐⭐⭐ |
| 8. Publications & demo | ⏳ | ⭐⭐⭐⭐ |

---

## Everything changed from the original plan, in one place

1. **Phase 2 split into 2a/2b** — off-the-shelf swap-in can start immediately; domain-adapted fine-tuning waits on Phase 3 data. Prevents "mock models replaced" from silently meaning two different things.
2. **Phase 3 moved to start in parallel with Phase 1**, not after Phase 2 — it's the gating dependency for 2b.
3. **Phase 5 security list expanded** — added timing side-channel and OOD-baseline drift-attack testing, since both mitigations already exist in code and are currently unvalidated.
4. **Phase 5 robustness scope corrected (this pass)** — `test_production.py` already has real fail-closed coverage for missing sensors/models; robustness work is extending that to real-model failure modes, not building it fresh. This is a narrower, cheaper task than the previous draft implied.
5. **Phase 5 regression re-baselining** — explicit line item for re-validating mock-calibrated thresholds against real-model score distributions.
6. **Phase 8 venue prioritization** — ranked IV/ITSC above general networking venues; made CCS/NDSS conditional on paper framing.
