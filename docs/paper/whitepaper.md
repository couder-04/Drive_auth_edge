# DriveAuth Edge

## Trust/Risk-Separated Offline Biometric Authorization for In-Vehicle Payments and Sensitive Commands

**White Paper** · July 2026 · Version 1.0  
**Companion (short form):** IEEE IV 2027 draft — [`iv2027-draft.md`](iv2027-draft.md)  
**Status:** Working manuscript (expand to PDF / arXiv when authors filled)  
**Repository:** https://github.com/couder-04/Drive_auth_edge  

**Authors:** [TBD]  
**Affiliation:** [TBD]  
**Correspondence:** [TBD]

> **Honesty bar.** This document reports measured Sprint-6 metrics and architectural
> invariants. It does **not** claim production-certified FAR/FRR, shipping fingerprint
> biometrics, fleet-ready behavioral biometrics on synthetic CAN, or ISO presentation-
> attack certification. See §11 and [`docs/security-assumptions.md`](../security-assumptions.md).

---

## Executive summary

Cabins are becoming payment surfaces—EV charging, tolls, parking, fleet disbursements—
while MFA patterns borrowed from phones assume free hands, free eyes, and a reliable
cellular path. Those assumptions fail while driving. Co-located passengers can coerce
OTP, replay a short utterance, or present a phone screen to a driver-monitoring camera.

**DriveAuth Edge** is an offline, edge-run authorization stack that answers three
questions with *separate* scores:

| Score | Question | Allowed inputs |
|-------|----------|----------------|
| **Trust** | Is this the enrolled driver? | Voice / face / finger only |
| **Risk** | How unusual is this transaction? | Amount, payee, GPS, speed, zone, CAN behaviour |
| **Confidence** | Should we believe our scores on this capture? | Quality, OOD, modality agreement |

A deterministic **policy engine** (YAML thresholds, transaction tiers) maps those scores
to `ACCEPT` · `STEP_UP_REQUIRED` · `REJECT` without a second end-to-end ML fusion head.
Biometric probes escalate **Voice → Face → Finger** with early-stop for UX and an
explicit **security floor** (static multi-factor AND) for audit and ablation.

**What we measured (July 2026):**

- Voice EER ≈ 0.215 · ROC-AUC ≈ 0.887; face (PAD-gated) EER ≈ 0.399 · ROC-AUC ≈ 0.652  
- Face PAD APCER / BPCER ≈ 0.348 / 0.0 · operational attack reject ≈ 0.65  
- Risk head val ROC-AUC ≈ 0.996 on a 50k synthetic-labelled txn set  
- NVIDIA Thor Phase-2a micro / high-value p95 ≈ **7.7 / 9.2 ms** (CUDA ECAPA + face)  
- Early-stop vs security-floor ablation at balanced voice bar: FRR 0.05 vs 1.0  

**What remains open:** fingerprint sensor + SDK, real CAN recorder dumps, live Nova
telematics GPS, and retrain of Risk at ~5k real labels.

---

## Table of contents

1. [Introduction](#1-introduction)  
2. [Problem analysis](#2-problem-analysis)  
3. [Related work](#3-related-work)  
4. [Threat model and design invariants](#4-threat-model-and-design-invariants)  
5. [System architecture](#5-system-architecture)  
6. [Policy engine, tiers, and fraud ladder](#6-policy-engine-tiers-and-fraud-ladder)  
7. [Models and Stage-2 heads](#7-models-and-stage-2-heads)  
8. [Edge deployment](#8-edge-deployment)  
9. [Datasets and evaluation protocol](#9-datasets-and-evaluation-protocol)  
10. [Results](#10-results)  
11. [Security properties, testing, and limitations](#11-security-properties-testing-and-limitations)  
12. [Integration surfaces](#12-integration-surfaces)  
13. [Discussion and lessons](#13-discussion-and-lessons)  
14. [Future work](#14-future-work)  
15. [Conclusion](#15-conclusion)  
16. [References](#16-references)  
Appendix A · [Artifact map](#appendix-a--artifact-map)  
Appendix B · [Integrator checklist](#appendix-b--integrator-checklist)

---

## 1. Introduction

Every year the vehicle cabin absorbs more financial and privileged actions: pay for
charging, authorize a toll, unlock a high-value HVAC or charging command, disburse fleet
expense. The industry instinct is to reuse phone MFA—SMS OTP, authenticator apps, or
“scan face again.” That instinct fails under motion, intermittency, and presence.

DriveAuth Edge was extracted from the Nova in-vehicle agent stack and hardened as a
standalone library with:

- Pluggable biometric matchers (ONNX / SpeechBrain)  
- A Risk head (LightGBM → ONNX) on transaction and vehicle context  
- A Confidence scorer over quality and out-of-distribution (OOD) signals  
- A human-auditable policy YAML surface  
- A Voice → Face → Finger escalation ladder  
- Mac + NVIDIA Thor profiles and a Sprint-6 benchmark suite  

### 1.1 Contributions

1. **Enforced Trust / Risk / Confidence separation** so context never inflates
   biometric identity and compliance can change bars without retraining fusion.  
2. **Staged ladder with published security floor** — early-stop as UX optimization,
   static AND MFA as the ablation baseline, hard Risk / fraud locks as irreversible
   gates.  
3. **Edge evidence** — mock and live-model latency on Mac and Thor; ONNX packing.  
4. **Evaluation package with an honesty bar** — FAR/FRR/EER/ROC, PAD, risk, ablations,
   timing and OOD-drift tests, plus explicit non-claims for hardware-gated modalities.  
5. **Open artifacts** — policy, models, tests, security-assumptions document, dashboard
   demo path.

### 1.2 Non-contributions (deliberate)

We do not claim a new state-of-the-art voice or face backbone. ECAPA-TDNN and
MobileFaceNet are off-the-shelf; Stage-2 work focuses on calibrators and face PAD.
Novelty is the **authorization architecture and policy surface** for intelligent-vehicle
payments, not a competition entry on VoxCeleb or LFW.

---

## 2. Problem analysis

### 2.1 Why phone MFA breaks in the cabin

| Failure mode | Mechanism | Consequence |
|--------------|-----------|-------------|
| Friction under motion | OTP / app / static multi-bio AND | Eyes-off-road; features get disabled |
| Co-located adversary | Passenger coerces code or presents replay/screen | OTP / naive face fail |
| Offline gaps | Tunnel / rural / airplane mode | Cloud MFA unavailable when needed |
| Context conflation | GPS/amount folded into “trust” | Unauditable identity vs risk mix |

### 2.2 Design requirements

R1. **Offline-first decision** for ACCEPT / REJECT on the edge host.  
R2. **Biometric identity independent of geo/amount.**  
R3. **Auditable thresholds** changeable without model retrain.  
R4. **Fail closed** on missing sensors, matcher crash, or missing OOD baselines.  
R5. **Interactive latency** for cabin UX (target: tens of ms for live biometrics on
automotive-class GPU; Phase-1 mock budget 10 ms p95).  
R6. **Honesty** — do not market proxy finger / synth CAN as production FAR/FRR.

### 2.3 What went wrong historically (internal motivation)

Earlier pipeline drafts allowed behavioural driving scores and GPS context to influence
a fused “trust” quantity—conflating *who you are* with *where/how you drive*. A genuine
driver in an unfamiliar city would look “less trusted,” or worse, anomaly features could
be misread as identity evidence. DriveAuth Edge’s central fix: **behaviour and location
feed Risk only; Trust is biometric-only.**

---

## 3. Related work

**In-vehicle authentication.** Key fobs, phone pairing, driver monitoring systems
(DMS), and continuous CAN-style soft biometrics. We treat driving-style anomaly as a
Risk feature, not as Trust inflation.

**Multimodal biometric fusion.** Score- and feature-level fusion dominate the
literature. Cabin payment systems that let amount or GPS modify an identity score create
compliance and audit problems. We keep fusion biometric-only and place context in Risk.

**Speaker and face recognition at the edge.** ECAPA-TDNN [1] and MobileFaceNet-class
embedders [2] are production-grade baselines. Our contribution is wiring, calibration,
PAD, and policy—not a new embedding architecture.

**Presentation attack detection.** Face PAD surveys [3] motivate Stage-2 heads. We
report APCER/BPCER on our attack set but do not claim ISO certification.

**Payment risk / fraud.** Transaction monitoring (amount novelty, beneficiary, geo) is
standard in fintech [4]. We embed a Gradient-Boosted Tree risk head as a first-class
score with hard ceilings independent of biometric Confidence.

**Side channels.** Escalation ladders can leak early-stop via timing. We implement an
optional constant-time pad and test it; default remains off for UX latency.

---

## 4. Threat model and design invariants

### 4.1 In-scope adversaries

| Actor / scenario | Goal | Intended response |
|------------------|------|-------------------|
| Unauthorized cabin user | Approve payment as enrolled driver | Ladder fails → REJECT (or guest STEP_UP for PIN) |
| Replay / presentation | Pass voice/face with recording or screen | QualityGate + face PAD + OOD degrade; fail closed on weak probes |
| OOD / baseline poison | Slowly drift enrollment / OOD stats | OOD refresh gated on independently strong auth |
| Risky genuine session | Novel payee, remote GPS, high speed | Risk ceiling / fraud ladder → REJECT or raised rigor |
| Timing observer | Infer early-stop from latency | Optional wall-clock pad |
| Missing / crashed sensor | Force ACCEPT via absence | Unavailable modality does not contribute; fail closed when required |

### 4.2 Out of scope (integrator / platform)

- Physical theft of the driver’s OTP phone  
- Compromised host OS, model-store keys, or dashboard process  
- Network MITM on assumed-trusted in-vehicle IPC  
- Exhaustive certification of every staged path (disable escalation for static parallel
  probes if required)

### 4.3 Architectural invariants

1. **Trust ≠ Risk.** GPS, speed, amount, beneficiary novelty, CAN behaviour never raise
   biometric Trust.  
2. **Accept/Reject is ladder-driven.** Policy applies hard gates; it does not invent a
   fourth biometric.  
3. **Fail closed.** Missing required captures, matcher timeout/crash, missing OOD
   baselines, Risk ≥ hard ceiling → deny / escalate, never silent ACCEPT.  
4. **Deterministic policy.** Thresholds in `policy.yaml` / `DRIVEAUTH_*`.  
5. **Audit without raw biometrics.** Metadata and scores only.  
6. **No OTP mid-ladder.** Cellular OTP / offline PIN are step-up fallbacks after the
   biometric path, not substitutes for a failed finger probe in the middle of escalation.

### 4.4 Trust boundary

```
Trusted:     DriveAuth process + profile store (templates, OOD stats, fraud state)
Assumed:     Live mic · camera · finger SDK · vehicle GPS/CAN (when wired)
Untrusted:   Cabin occupants · utterances · payees · replay media · adversarial UI GPS
Demo-only:   ManualScores / dashboard sliders — NOT a security control
```

---

## 5. System architecture

### 5.1 Pipeline

```text
Sensor capture
    │
    ▼
QualityGate ── bad capture ──▶ skip matcher (fail closed if required)
    │
    ▼
Matchers (parallel capability; ladder sequences probes)
    ├── VoiceMatcher     (ECAPA-TDNN ± calibrator)
    ├── FaceMatcher      (MobileFaceNet ± PAD ± calibrator)
    └── FingerMatcher    (FingerNet / vendor SDK when HW present)
    │
    ├──▶ TrustFusion          → Trust     [biometrics ONLY]
    ├──▶ RiskModel            → Risk      [GPS/CAN/amount/behaviour]
    ├──▶ OODDetector + Quality ─▶ Confidence
    │
    ▼
PolicyEngine (tiers: micro / standard / high_value / guest)
    │
    ▼
ACCEPT | STEP_UP_REQUIRED | REJECT
    ├── FraudStateMachine adjusts rigor over time
    ├── STEP_UP → OTP (cellular) → offline PIN+biometric fallback
    └── AuditLog (metadata only)
```

### 5.2 Module map

| Module | Responsibility |
|--------|----------------|
| `api.py` | Public `DriveAuth` — `authenticate` · `intercept` · `require_auth` |
| `decision_engine.py` | Quality → matchers → scores → policy; optional timing pad |
| `fusion.py` | Trust fusion + Confidence scorer |
| `risk_model.py` | Transaction/vehicle Risk (ONNX or additive fallback) |
| `policy_engine.py` | Deterministic tier rules |
| `fraud_state.py` | Normal → Elevated → Heightened → Locked |
| `escalation.py` | Voice → Face → Finger ladder plan |
| `matchers/` | Pluggable biometric backends |
| `profile_store.py` | Templates, OOD stats, atomic writes, OOD refresh gate |
| `orchestrator.py` | Optional dynamic trust weights (PolicyMLP) |

### 5.3 Score definitions

**Trust ∈ [0,1]** — weighted combination of available modality match scores (defaults:
voice 30%, face 40%, finger 30%). Quality can down-weight a modality; GPS/amount never
enter.

**Risk ∈ [0,1]** — unusualness of the transaction/context: amount z-score, beneficiary
novelty, distance from home, geofence, moving-fast, behavioral anomaly. Runs on CPU.

**Confidence ∈ [0,1]** — reliability of this capture: penalizes modality disagreement,
low SNR / blur, OOD flags, hardware faults, missing baselines. Low Confidence → STEP_UP
even if Trust looks strong.

### 5.4 Staged ladder

```text
Voice score ≥ bar? ──yes──▶ ACCEPT (early-stop, if Risk/fraud/Confidence allow)
        │ no
        ▼
Face score ≥ bar?  ──yes──▶ ACCEPT
        │ no
        ▼
Finger ≥ bar?      ──yes──▶ ACCEPT
        │ no
        ▼
REJECT (or STEP_UP on guest / exhausted high-value paths)
```

Early-stop is a **UX optimization**. The **security floor** for analysis is static
multi-factor AND (force full MFA). Integrators can set `DRIVEAUTH_ESCALATION_ENABLED=0`
for certification-style parallel probes.

Hard gates that override early-stop desire: fraud lock, Risk ≥ reject ceiling,
Confidence below floor, missing required modalities.

---

## 6. Policy engine, tiers, and fraud ladder

### 6.1 Policy bands (defaults)

| Variable | Default | Meaning |
|----------|---------|---------|
| `DRIVEAUTH_RISK_APPROVE` | 0.35 | Risk ≤ → low-risk band |
| `DRIVEAUTH_RISK_REJECT` | 0.80 | Risk ≥ → hard reject |
| Trust accept (micro / std / high) | 0.70 / 0.78 / 0.85 | Tiered Trust bars |
| `DRIVEAUTH_TRUST_REJECT` | 0.48 | Trust below → reject |
| `DRIVEAUTH_CONF_FLOOR` | 0.55 | Confidence below → step-up |
| Ladder voice / face / finger | 0.72 / 0.70 / 0.70 | Per-modality early-accept |

Exact keys live in `driveauth/policy.yaml` as `${ENV:default}` placeholders so fleets
can change bars without code edits.

### 6.2 Transaction tiers

| Tier | Trigger (illustrative) | Behaviour |
|------|------------------------|-----------|
| `micro` | Low amount, known beneficiary | Single strong modality may suffice |
| `standard` | Default | Escalation as configured; ambiguous → STEP_UP |
| `high_value` | High amount or unknown beneficiary | Higher Trust bar; often mandatory step-up |
| `guest` | Guest profile | PIN/card path — biometrics skipped |

Currency/thresholds are policy-local (e.g. INR demos in internal docs); integrators
rebind to fleet economics.

### 6.3 Fraud state machine

Repeated anomalies raise rigor: Normal → Elevated → Heightened → Locked. Locked states
force REJECT independent of a lucky biometric draw. Bootstrap periods cap amounts until
enough history exists (`BOOTSTRAP_MIN_TXNS` / days — defaults, not fleet-tuned).

---

## 7. Models and Stage-2 heads

### 7.1 Inventory

| Component | Backend | Notes |
|-----------|---------|-------|
| Voice | ECAPA-TDNN (SpeechBrain) | Enrolled templates; Stage-2 calibrator ONNX |
| Face | MobileFaceNet ONNX | PAD + calibrator; PAD reject → score 0 path |
| Finger | Vendor SDK / mock | ManualScores until HW — **proxy only** |
| Behavioral | LSTM bake-off winner → ONNX | **Synth CAN** — re-bake on recorder dumps |
| Risk | LightGBM → `risk_gbt.onnx` | 50k txn training; additive fallback if missing |
| Trust fusion | Static weights (Stage 1) / logreg ONNX (Stage 2) | Biometric inputs only |

### 7.2 Stage-2 philosophy

Frozen 2a backbones + trainable score adapters:

- Voice calibrator maps raw similarity toward better calibrated accept probabilities  
- Face PAD estimates presentation-attack likelihood; calibrator adjusts live scores  
- Trust fusion logreg learns weights on biometric features without consuming Risk inputs  

Ablation (§10.4): PAD+calibrators leave voice EER unchanged on our set but cut mean face
**attack** score (≈0.50 → ≈0.18) and yield operational attack reject ≈0.65.

### 7.3 Risk features (representative)

`amount_z`, `beneficiary_novel`, `dist_from_home`, `out_of_zone`, `moving_fast`,
`behavior_anomaly`, plus related schema fields in `RiskContext`. Val ROC-AUC ≈ 0.9955,
Brier ≈ 0.026 on the synthetic-labelled split—**not** live card-fraud proof.

### 7.4 Behavioral bake-off

LSTM / GRU / GBM compared on current behavioral windows; LSTM won and exported. Winner
AUC on **synthetic** windows is not production biometric quality. Real CAN dumps under
`data/*/behavioral/{genuine,attack}/` (8-feature schema) are required before citing
fleet FAR/FRR.

---

## 8. Edge deployment

### 8.1 Phase 1 — mock pipeline budget

Budget: mock auth **p95 ≤ 10 ms**.

| Platform | p50 | p95 | vs budget |
|----------|-----|-----|-----------|
| Mac (M-class) | 0.7 ms | **0.8 ms** | PASS |
| NVIDIA Thor | 0.6 ms | **0.9 ms** | PASS |

### 8.2 Phase 2a — live voice + face

| Platform | Scenario | p95 |
|----------|----------|-----|
| Mac | micro | ≈ 37.6 ms |
| Thor (CUDA EP) | micro | ≈ **7.7 ms** |
| Thor (CUDA EP) | high-value | ≈ **9.2 ms** |

Profiles: `phases/phase2a-mac.txt`, `phases/phase2a-thor.txt`. ONNX Runtime build notes
for Thor SM110 are in Phase 2a docs.

### 8.3 Packaging principles

- Prefer ONNX for matchers and Stage-2 heads  
- CPU Risk path so GPU contention on biometrics does not stall policy  
- Same store paths for enroll and auth (`DRIVEAUTH_*_STORE`)  
- Optional constant-time pad trades latency for timing side-channel resistance  

---

## 9. Datasets and evaluation protocol

### 9.1 Phase 3 collections (driver1)

| Modality | Genuine / enroll | Attacks / OOD | Notes |
|----------|------------------|---------------|-------|
| Voice | Enroll 8 · genuine 20 · noisy 5 | Silent, replay, other_speaker · TTS OOD | |
| Face | Enroll + genuine (own-face) | Blur · side · screen · other-id OOD | RDJ retired |
| Finger | Synth ridge PNGs | Synth | Replace with sensor |
| Behavioral | Synth CAN windows | Synth attacks | Replace with recorder |
| Transactions | 50k rows | Labelled for Risk train/val | Synthetic labels |

### 9.2 Sprint 6 protocol

`scripts/phase6_benchmark.py` produces `phases/phase6_sprint6.json` and the tables in
`phases/phase6.md`:

- Per-modality EER / ROC on Stage-2 scores  
- PAD APCER/BPCER and operational attack reject  
- Risk classification + calibration  
- System FAR/FRR for OTP-only, single-modality, static MFA, staged ladders  
- Ablations: early-stop vs AND; voice-bar sweep; Stage-2 vs raw 2a  

Finger variants marked `*_proxy` use ManualScores-style stand-ins.

### 9.3 Security tests

- Timing pad — `tests/test_security_sprint1.py`  
- OOD-drift / refresh gating — same + `tests/test_ood_stage1.py`  
- Real-model failure modes (crash / timeout / missing) — `tests/test_phase5_failure_modes.py`  
- Threshold re-baseline guards — `tests/test_phase5_thresholds.py`  
- Suite size — 155+ pytest cases (Phase 5 exit); grew through Phase 6/standalone  

---

## 10. Results

Numbers below match `phases/phase6.md` as of 2026-07-15. Re-run the benchmark before
camera-ready or arXiv freeze.

### 10.1 Sprint 6 summary

| Category | Metric | Value |
|----------|--------|-------|
| Voice | EER / ROC-AUC | 0.2154 / 0.8866 |
| Face (PAD-gated) | EER / ROC-AUC | 0.3989 / 0.6522 |
| PAD | APCER / BPCER | 0.3478 / 0.0 |
| PAD | Attack reject (ops) | 0.6522 |
| Risk | Val ROC-AUC / Acc / F1 | 0.9955 / 0.9669 / 0.9415 |
| Risk | Brier | 0.026071 |
| Latency Mac 2a | micro p95 | 37.6 ms |
| Latency Thor 2a | micro / high p95 | 7.7 / 9.2 ms |
| OOD Stage 1 | Voice / face reject | 1.0 / 1.0 |
| Behavioral (synth) | Winner AUC | 1.0 (LSTM) — **synth only** |

### 10.2 System comparison (shipping ladder bars)

Bars: voice ≥ 0.72 · face ≥ 0.70 · finger ≥ 0.70 (proxy).

| System | FAR | FRR | Genuine accept | Notes |
|--------|-----|-----|----------------|-------|
| `otp_only` | 0.0 | 1.0 | 0.0 | Always STEP_UP; FAR assumes OTP channel secure |
| `voice_only` | 0.0 | 1.0 | 0.0 | |
| `face_only` | 0.0 | 1.0 | 0.0 | |
| `finger_only_proxy` | 0.0 | 0.0 | 1.0 | **Not** production finger quality |
| `static_mfa_voice_and_face` | 0.0 | 1.0 | 0.0 | Security floor style |
| `staged_voice_face` | 0.0 | 1.0 | 0.0 | No finger |
| `staged_full_proxy` | 0.0 | 0.0 | 1.0 | Finger proxies |

Shipping bars prefer **FAR≈0 with high FRR** on current small eval sets—security over
UX until face overlap improves. Do **not** apply `phase2b_suggested.env` as default.

### 10.3 Ablation A1 — early-stop vs security floor

At **balanced** voice bar 0.525 (face 0.70):

| Variant | FAR | FRR | Early-stop voice rate |
|---------|-----|-----|------------------------|
| Staged early-stop | 0.1111 | 0.05 | 0.95 |
| Force full MFA (AND) | 0.0 | 1.0 | 0 |
| Δ (early − full) | +0.1111 | −0.95 | — |

Interpretation: early-stop recovers UX when voice clears; static AND is the conservative
floor. Shipping bars (0.72) yield FAR=0 / FRR=1 for both variants on this set—use the
balanced row for the UX trade-off narrative.

### 10.4 Ablation A2 — voice-bar sweep

| Voice bar | FAR | FRR | Early-stop rate |
|-----------|-----|-----|-----------------|
| 0.50 | 0.111 | 0.00 | 1.00 |
| 0.55 | 0.111 | 0.05 | 0.95 |
| 0.60 | 0.056 | 0.30 | 0.70 |
| 0.65 | 0.000 | 0.90 | 0.10 |
| ≥0.675 | 0.000 | 1.00 | 0.00 |

Full sweep including 0.525–0.850: `phases/phase6.md` §A2.

### 10.5 Ablation A3 — Stage-2 vs raw 2a

| | Voice EER | Face EER | Face attack mean | PAD attack reject |
|--|-----------|----------|------------------|-------------------|
| Stage 2 | 0.2154 | 0.3989 | 0.1763 | 0.6522 |
| Raw 2a | 0.2154 | 0.3957 | 0.4975 | 0 |

PAD and calibrators matter more than swapping another backbone once embeddings are
“good enough” for enrollment.

---

## 11. Security properties, testing, and limitations

### 11.1 Controls that exist today

| Control | Location | Default note |
|---------|----------|--------------|
| Ladder + modality bars | `escalation.py` · `policy.yaml` | voice 0.72 · face 0.70 · finger 0.70 |
| Fraud rigor / lock | `fraud_state.py` | Lock → REJECT |
| Risk hard ceiling | `policy_engine.py` | reject @ 0.80 |
| Face PAD + calibrators | Stage-2 ONNX | Bypass only for eval (`STAGE2_RAW`) |
| OOD detector + refresh gate | `ood_detector.py` · `profile_store` | Missing baseline → fail closed |
| Decision cache limits | `api.require_auth` | No REJECT/STEP_UP reuse; epoch checks |
| Timing pad | `DecisionEngine._pad_timing` | **Off** unless env > 0 |
| Atomic profile writes | `profile_store.py` | `.tmp` + replace |

### 11.2 Explicit non-claims

| Do not claim | Reality |
|--------------|---------|
| Production FAR/FRR certified | Small Phase-3 / Stage-2 eval sets; face still weak vs voice |
| Behavioral biometrics fleet-ready | Synth CAN bake-off only |
| Fingerprint verification shipping | Mock / ManualScores until SDK + captures |
| Deepfake / ASVspoof complete | Quality + calibrator depth, not full anti-spoof suite |
| PAD stops all replays | Feature PAD; APCER reported — not ISO cert |
| Constant-time by default | Pad is opt-in |
| OTP comparison proves superiority | Bench FAR=0 assumes OTP channel security |
| Blindly lower bars via suggested env | Keep conservative until face attack overlap improves |

### 11.3 Residual product risks

1. Fairness of brightness/blur gates across skin tones and cabin lighting unvalidated.  
2. Bootstrap duration defaults are not fleet-tuned.  
3. Staged probes widen certification state space.  
4. Until Nova live GPS wiring, Risk can understate location/speed anomalies.  
5. Store encryption / TEE is an integrator concern beyond the demo store.

---

## 12. Integration surfaces

### 12.1 Library API (Nova path)

- `DriveAuth.authenticate(...)` — explicit auth  
- `DriveAuth.intercept(...)` — agent command gate  
- `require_auth` — decorator/helper with decision cache rules  
- `update_vehicle_context` / behavioral updates — keep Risk fresh  

Contract details: `docs/integration.md`.

### 12.2 Standalone product path

OpenRouter STT/TTS/LLM intent slot-fill, Maps home pin → `dist_from_home_km`, live
ECAPA/face on `/standalone`, enrollment on `/register`, manual sliders on `/manual`.
Same decision engine underneath. See `docs/standalone.md`. Finger remains manual until HW.

### 12.3 Dashboard demo

Presets: micro → ACCEPT; low voice → escalate; low biometrics → REJECT. GIF:
`docs/demo.gif`. Phase-8 full video storyboard: `docs/paper/demo-video.md`.

---

## 13. Discussion and lessons

1. **Separate scores beat a clever fusion head** when compliance must change rules weekly.  
2. **Early-stop is an ablation, not a slogan** — publish FAR/FRR against the security floor.  
3. **PAD and calibrators often beat backbone swaps** for cabin presentation threats.  
4. **Own-face enroll beats celebrity stills** before touching thresholds.  
5. **Write security assumptions before marketing** — it keeps Sprint-6 interpretation honest.  
6. **Shipping high FRR can be correct** — FAR=0 / FRR=1 at strict bars is a policy choice,
   not a silent failure, if UX recovery is documented via the balanced-bar ablation.

Venue note: IEEE IV / ITSC fit the automotive systems story. CCS/NDSS-style framing is
appropriate only if the manuscript leads with timing, OOD-drift, and security-floor
analysis rather than cabin UX architecture.

---

## 14. Future work

| Priority | Work |
|----------|------|
| P0 | Fingerprint vendor SDK + real captures; drop ManualScores in prod claims |
| P0 | Real CAN windows → re-run behavioral bake-off → re-enroll |
| P1 | Wire Nova telematics into `update_vehicle_context` every auth |
| P1 | Retrain Risk at ~5k real labelled transactions; overfit audit |
| P1 | Re-check face overlap; only then consider `phase2b_suggested.env` |
| P2 | Fairness study on quality gates across lighting / skin tones |
| P2 | Optional default timing pad profiles for untrusted IPC observers |
| P2 | Submit IV 2027 short paper; publish demo video; freeze PDF of this white paper |
| P3 | TEE / encrypted store hardening as integrator reference design |

---

## 15. Conclusion

DriveAuth Edge argues that intelligent-vehicle payment authorization benefits less from
a monolithic identity–context fusion head than from:

1. **Auditable Trust / Risk / Confidence separation**,  
2. A **staged biometric ladder** with a measurable security floor,  
3. **Edge latency** compatible with cabin interaction, and  
4. An **honesty bar** that refuses to oversell hardware-gated modalities.

We release architecture docs, policy YAML, ONNX heads, Sprint-6 tables, and security
tests alongside this white paper. The short-form conference companion targets IEEE IV
2027; this manuscript is the long-form systems record.

---

## 16. References

[1] B. Desplanques, J. Thienpondt, and K. Demuynck, “ECAPA-TDNN: Emphasized Channel
Attention, Propagation and Aggregation in TDNN Based Speaker Verification,”
*Interspeech*, 2020.

[2] S. Chen, Y. Liu, X. Gao, and Z. Han, “MobileFaceNets: Efficient CNNs for Accurate
Real-Time Face Verification on Mobile Devices,” *CCBR*, 2018. (and related lightweight
FR literature)

[3] Surveys on face presentation attack detection / liveness (ISO/IEC 30107 context).

[4] Payment fraud detection and transaction monitoring literature (gradient boosting /
graph features in fintech risk).

[5] IEEE Intelligent Vehicles Symposium and ITSC proceedings — cabin HMI, DMS, IV security.

[6] DriveAuth Edge artifacts (2026): `phases/phase6.md`, `docs/security-assumptions.md`,
repository https://github.com/couder-04/Drive_auth_edge

*[Expand with full IEEE-style bibliography before PDF freeze.]*

---

## Appendix A — Artifact map

| Artifact | Path |
|----------|------|
| Policy | `driveauth/policy.yaml` |
| Sprint 6 JSON / write-up | `phases/phase6_sprint6.json` · `phases/phase6.md` |
| Security assumptions | `docs/security-assumptions.md` |
| Architecture | `architecture/overview.md` · `architecture/trust-risk-separation.md` |
| IV short paper | `docs/paper/iv2027-draft.md` |
| Demo video kit | `docs/paper/demo-video.md` |
| Phase 8 tracker | `phases/phase8.md` |
| Benchmark runner | `scripts/phase6_benchmark.py` |
| Thor / Mac profiles | `phases/phase2a-thor.txt` · `phases/phase2a-mac.txt` |

## Appendix B — Integrator checklist

Before calling a deployment “secure”:

- [ ] Real voice + own-face enrolled; recalibrate; keep bars conservative  
- [ ] Finger SDK emitting live `ModalityResult` (no dashboard stand-ins)  
- [ ] Real CAN → re-bake behavioral → re-enroll  
- [ ] Telematics calls `update_vehicle_context` every auth  
- [ ] Enable timing pad if IPC observers are in scope  
- [ ] `DRIVEAUTH_USE_MOCK=0`; Stage-2 heads loaded  
- [ ] `pytest` + `scripts/phase6_benchmark.py` after any threshold change  

---

## Document control

| Field | Value |
|-------|-------|
| Title | DriveAuth Edge White Paper |
| Version | 1.0 |
| Date | 2026-07-15 |
| Classification | Public (after author approval) |
| Metrics freeze | Re-run `phase6_benchmark.py` before PDF / arXiv |
| Next | Authors · PDF layout · IV template port of short form |
