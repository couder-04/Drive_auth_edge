# DriveAuth Edge: Trust/Risk-Separated Offline Biometric Authorization for In-Vehicle Payments

> **Target:** IEEE IV 2027 regular paper (≤6 pages).  
> **Status:** Working markdown draft — port to IEEE template before submission.  
> **Long form:** [`whitepaper.md`](whitepaper.md) · tracker [`phases/phase8.md`](../../phases/phase8.md) · numbers [`phases/phase6.md`](../../phases/phase6.md).  
> **Do not claim:** production finger FAR/FRR, synth-CAN behavioral as fleet-ready, or certified PAD — see [`docs/security-assumptions.md`](../security-assumptions.md).

**Authors:** [TBD]  
**Affiliation:** [TBD]

---

## Abstract

In-vehicle payments and privileged cabin commands are a poor fit for phone-centric MFA. Drivers lack free hands and eyes; cellular paths fail in tunnels; a co-located passenger can coerce OTP or present a replayed voice or phone-screen face. We present **DriveAuth Edge**, an offline biometric authorization stack that separates three scores that are often fused incorrectly: **Trust** (is this the enrolled driver?), **Risk** (how unusual is this transaction?), and **Confidence** (should we trust this capture?). A deterministic policy engine maps score bands and transaction tiers to ACCEPT / STEP_UP / REJECT without a second end-to-end ML head. Biometric probes escalate Voice → Face → Finger with early-stop for UX and an explicit security floor. We deploy on Mac and NVIDIA Thor (Phase-2a micro p95 ≈ 7.7 ms with CUDA ECAPA + face) and evaluate Sprint-6 FAR/FRR/EER/ROC, PAD, risk, and early-stop ablations — reporting also what remains hardware-gated (fingerprint sensor, real CAN). Open artifacts: policy YAML, ONNX heads, and security tests for timing pads and OOD-drift gating.

**Index Terms**—Intelligent vehicles, biometrics, edge AI, in-vehicle payments, authentication, Trust/Risk separation.

---

## I. Introduction

Cabins are becoming payment surfaces: EV charging, tolls, parking, fleet disbursements. The default MFA pattern—SMS OTP, authenticator apps, or always-on multi-biometric AND gates—assumes a cooperative primary user with spare attention and a reliable wide-area channel. Those assumptions break while driving.

Three cabin-specific failure modes motivate a different design:

1. **Friction under motion.** OTP and static “voice AND face every time” increase eyes-off-road and get disabled in practice.
2. **Co-located adversaries.** A passenger can request a spoken code, replay a short utterance, or hold a screen to a DMS camera—threats phone MFA papers over.
3. **Offline requirement.** Tunnels and rural corridors still need a fail-closed local decision for privileged actions.

**Contribution.** DriveAuth Edge is an open, edge-run authorization library extracted from a larger in-vehicle agent stack (Nova). This paper’s systems contribution is the **enforced separation of Trust, Risk, and Confidence**, a **staged biometric ladder** with measurable early-stop versus security-floor trade-offs, and an **evaluation package** that reports latency on automotive-relevant edge hardware alongside honest limits (fingerprint HW, synthetic CAN, synthetic risk labels).

We deliberately do **not** claim a new SOTA single-modal biometric backbone. ECAPA-TDNN and MobileFaceNet are off-the-shelf; Stage-2 heads add score calibrators and a face presentation-attack detector (PAD). The novelty is the **authorization architecture and policy surface** for intelligent-vehicle payments.

---

## II. Related Work

**In-vehicle authentication** spans key fobs, phone pairing, driver monitoring (DMS), and emerging multimodal biometrics. Continuous authentication from CAN/driving style is often framed as soft biometrics; we treat behavioral anomaly as a **Risk** feature, never as Trust inflation.

**Multimodal MFA and fusion.** Classic score/feature fusion blends identity with context. Cabin systems that let GPS or amount modify a “trust” score conflate *who* with *what*—complicating audit and compliance. Our policy keeps Risk and Trust on separate inputs.

**Edge biometrics.** SpeechBrain ECAPA-TDNN and MobileFaceNet ONNX are representative production-grade embedders. Our latency target is interactive cabin UX on NVIDIA Thor-class devices, not cloud round-trips.

**Payment risk.** Transaction monitoring (amount novelty, beneficiary, geo) is standard in fintech; we embed a LightGBM→ONNX risk head as a first-class score next to biometrics, with hard Risk ceilings independent of biometric confidence.

---

## III. System Architecture

### A. Score separation

| Score | Question | Allowed inputs |
|-------|----------|----------------|
| Trust | Enrolled driver? | Voice / face / finger match scores only |
| Risk | Unusual transaction / context? | Amount, beneficiary novelty, GPS/home distance, speed, zone, behavioral anomaly |
| Confidence | Trust our scores this capture? | Quality flags, OOD indicators, modality disagreement |

Trust fusion never consumes GPS, amount, or driving style. Risk never raises biometric Trust.

### B. Pipeline

Sensors and transaction context enter quality gates, then parallel matchers (voice ECAPA-TDNN, face MobileFaceNet + PAD, fingerprint when HW available). Trust, Risk, and Confidence feed a **YAML policy engine** over tiers (micro / standard / high_value / guest) → ACCEPT | STEP_UP_REQUIRED | REJECT. A fraud state machine raises rigor over repeated anomalies; audit logs store metadata only (no raw biometrics).

Optional Nova agent path: `DriveAuth.intercept()` for command authorization. Standalone product path uses cloud STT/TTS/intent with the same local biometric decision (out of scope for the IV evaluation core).

### C. Staged ladder

Probes escalate **Voice → Face → Finger**:

- Strong voice can early-stop ACCEPT (UX).
- Ambiguous voice escalates to face; then finger.
- Hard Risk / fraud lock / confidence floor force STEP_UP or REJECT regardless of early-stop desire.
- Static MFA (AND of modalities) is the **security floor** ablation baseline.

Escalation is configurable; integrators can disable early-stop for certification-style static probes.

---

## IV. Models and Deployment

| Component | Backend | Notes |
|-----------|---------|-------|
| Voice | ECAPA-TDNN (SpeechBrain) | Enrolled templates; Stage-2 calibrator |
| Face | MobileFaceNet ONNX | PAD + calibrator; attack reject measured |
| Finger | Vendor SDK / mock | Metrics marked proxy until sensor HW |
| Behavioral | LSTM bake-off winner → ONNX | **Synth CAN** — re-bake on recorder dumps |
| Risk | LightGBM → `risk_gbt.onnx` | 50k txn training set (synthetic labels) |
| Trust fusion | Static weights (Stage 1) / logreg ONNX (Stage 2) | Biometric-only inputs |

**Edge.** Phase-1 mock auth p95 ≤ 10 ms on Mac and Thor. Phase-2a live voice+face on Thor with CUDA EP: micro / high-value scenario p95 ≈ **7.7 / 9.2 ms** (`phases/phase2a-thor.txt`). Mac Phase-2a micro p95 ≈ 37.6 ms (CPU-class path). Models export ONNX for reproducible edge packing.

---

## V. Evaluation

Artifacts: `scripts/phase6_benchmark.py` → `phases/phase6_sprint6.json`. Security tests: timing pad and OOD-drift (`tests/test_security_sprint1.py`). Full suite >150 pytest cases including fail-closed paths.

### A. Biometrics, PAD, risk, latency (Sprint 6)

| Category | Metric | Value |
|----------|--------|-------|
| Voice | EER / ROC-AUC | 0.215 / 0.887 |
| Face (PAD-gated) | EER / ROC-AUC | 0.399 / 0.652 |
| Face PAD | APCER / BPCER | 0.348 / 0.0 |
| Face PAD | Attack reject (ops) | 0.652 |
| Risk | Val ROC-AUC / Brier | 0.996 / 0.026 |
| Latency Thor 2a | micro / high p95 | 7.7 / 9.2 ms |
| OOD Stage 1 | Voice / face reject | 1.0 / 1.0 |

Face genuine scores remain challenging at shipping ladder bars (≥0.70); we **do not** loosen policy via suggested env overrides until attack overlap improves.

### B. System comparison

Against OTP-only (always STEP_UP), single-modality bars, static voice∧face, and staged ladders. Finger results that use ManualScores proxies are labeled `*_proxy` and are **not** production biometric quality. Shipping bars often yield FAR=0 with FRR=1 on current small eval sets—security over UX by design.

### C. Ablation: early-stop vs security floor

At a **balanced** voice bar (0.525) with face bar 0.70:

| Variant | FAR | FRR | Early-stop voice rate |
|---------|-----|-----|------------------------|
| Staged early-stop | 0.111 | 0.05 | 0.95 |
| Force full MFA (AND) | 0.0 | 1.0 | 0 |

Early-stop improves UX when voice clears; static AND is the security floor. Voice-bar sweeps (`phases/phase6.md` §A2) show the FAR/FRR Pareto for ladder design.

### D. Stage-2 heads

PAD + calibrators leave voice EER unchanged on our set but cut mean face **attack** score (≈0.50 → ≈0.18) and yield operational attack reject ≈0.65—evidence that presentation defense and calibration matter more than another backbone swap for this cabin setting.

---

## VI. Security Properties and Limitations

**Enforced:** biometric-only Trust; Risk hard ceilings; fail-closed missing sensors/models; OOD refresh gated on independently strong auth; optional constant-time pad (`DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS`); no raw biometrics in audit.

**Limitations (explicit):**

- Fingerprint verification not shipping without vendor SDK + captures.
- Behavioral metrics on synthetic CAN only.
- Risk trained on synthetic transaction labels; retrain at ~5k real labels.
- PAD is feature-based, not ISO certification.
- Timing pad is **opt-in** (default off).
- OTP-only FAR=0 in benches **assumes** a secure OTP channel.

Threat assumptions and integrator checklist: public security assumptions document in the repository.

---

## VII. Conclusion

DriveAuth Edge shows that intelligent-vehicle payment authorization benefits less from a monolithic fusion head than from **auditable score separation**, a **staged ladder with a published security floor**, and **edge latency** compatible with cabin interaction. We release evaluation tables and security tests alongside honest non-claims for hardware-gated modalities. Future work: real fingerprint and CAN pipelines, live telematics GPS wiring, and fleet-tuned bars that remain fail-closed. The long-form systems record is the companion white paper [`whitepaper.md`](whitepaper.md).

---

## References (seed — expand in IEEE bib)

1. B. Desplanques et al., “ECAPA-TDNN,” Interspeech, 2020.  
2. MobileFaceNet / related lightweight face recognition literature.  
3. IEEE Intelligent Vehicles Symposium proceedings (cabin HMI, DMS).  
4. Payment fraud / transaction monitoring surveys (fintech risk).  
5. Presentation attack detection surveys (face PAD).  
6. DriveAuth Edge repository artifacts: Phase 6 benchmarks, security assumptions (self-cite after public DOI / arXiv if dual-published).

---

## Figure / table plan (for IEEE template)

| Fig/Tab | Content |
|---------|---------|
| Fig. 1 | Trust / Risk / Confidence block diagram (from README mermaid) |
| Fig. 2 | Voice→Face→Finger ladder with early-stop |
| Fig. 3 | Early-stop vs AND ablation (bar chart from §V-C) |
| Tab. I | Sprint 6 summary metrics |
| Tab. II | Latency Mac vs Thor |
| Tab. III | System comparison (OTP / static / staged) — mark proxies |

## Porting checklist

- [ ] Copy into IEEE conference LaTeX/Word template  
- [ ] Blind authors if required  
- [ ] Compress to ≤6 pages  
- [ ] Replace [TBD] authors  
- [ ] Verify every number still matches `phase6_sprint6.json` after re-run  
- [ ] Spell-check non-claims against `security-assumptions.md` §6  
