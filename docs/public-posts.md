# Public posts — DriveAuth Edge (Phase 7)

Copy-paste drafts for LinkedIn and Medium/Substack. Narrative follows
[`security-assumptions.md` §10](security-assumptions.md): problem → Trust/Risk/Confidence
separation → ladder + security floor → honest non-claims → evidence links.

**Repo:** https://github.com/couder-04/Drive_auth_edge  
**Demo GIF:** `docs/demo.gif` (attach on LinkedIn / embed on Medium)  
**Security doc:** [`docs/security-assumptions.md`](security-assumptions.md)  
**Benchmarks:** [`phases/phase6.md`](../phases/phase6.md)

Replace `[Your Name]` / LinkedIn tags as needed. Do **not** claim production
FAR/FRR for finger or synth-CAN behavioral metrics — see assumptions §6–7.

---

## 1. LinkedIn (technical post)

**Suggested title (first line):**  
Why OTP in the car is the wrong MFA — and what we built instead

**Body (≈1,300–1,600 chars — trim if needed for LinkedIn):**

```
In-cabin payments and “unlock HVAC / start charging” commands are a terrible fit for phone OTP.

You’re driving. The cabin is noisy. An attacker sitting next to you can ask for the code, replay a recording, or point a phone screen at the camera. Static “voice AND face every time” is safer — and punishingly slow.

DriveAuth Edge is an offline biometric authorization stack for in-vehicle payments and sensitive commands. The design bet is simple:

• Trust — “Is this the enrolled driver?” (voice → face → finger only)
• Risk — “How unusual is this transaction?” (amount, GPS, speed, beneficiary, driving behaviour)
• Confidence — “Should we trust our scores on this capture?” (quality, OOD, modality agreement)

Accept/Reject is ladder-driven (early-stop when a strong probe clears), with hard Risk ceilings and a fail-closed policy engine — YAML thresholds auditors can change without retraining models.

What we shipped (July 2026):
→ ECAPA voice + MobileFaceNet face on Mac and NVIDIA Thor (CUDA p95 ≈ 8–9 ms)
→ Stage-2 face PAD + score calibrators
→ Risk head (LightGBM→ONNX) on 50k txns
→ 155+ tests including timing pad + OOD-refresh gating
→ Sprint 6 FAR/FRR/EER/ROC ablations (early-stop vs security floor)

What we do *not* claim yet: production finger FAR/FRR (HW still gated), live card-fraud Risk, or synth-CAN behavioural biometrics as fleet-ready.

Open source + security assumptions + demo:
https://github.com/couder-04/Drive_auth_edge

If you work on automotive UX, payments risk, or edge biometrics — happy to compare notes.

#EdgeAI #Biometrics #Automotive #FinTech #CyberSecurity #ONNX
```

**Attach:** `docs/demo.gif` + optional screenshot of the dashboard (Trust / Risk / ladder result).

**Comment (optional, first reply):**  
Deep dive on Medium: *Building DriveAuth Edge…* — link after Medium publish.  
Architecture note: Trust never consumes GPS/amount; Risk never raises biometric Trust.

---

## 2. Medium / Substack (longform)

**Title:** Building DriveAuth Edge: Offline Biometric Authorization for In-Car Payments

**Subtitle:** Trust, Risk, and Confidence — and why we refused to fuse them into one ML head

**Tags:** Edge AI, Biometrics, Automotive, Security, ONNX, FinTech

---

### Draft

Every year the cabin becomes more of a payments surface: EV charging, tolls, parking, in-car retail, fleet disbursements. The UX instinct is to borrow phone MFA — SMS OTP, authenticator apps, “scan your face again.” That instinct fails in a moving vehicle.

OTP assumes eyes and hands are free. It assumes a cellular path. It assumes the attacker is remote. In the cabin, the attacker can be a passenger, a replayed voice note, or a phone screen held up to the camera. Asking for a six-digit code while the driver is in a tunnel is not a security feature; it’s friction that gets turned off.

**DriveAuth Edge** is our answer: an **offline**, edge-run authorization pipeline for in-vehicle payments and sensitive commands. It was extracted from the Nova AI stack and hardened as a standalone library with a dashboard, enrollment path, and documented security assumptions.

This post is the systems story — and the honesty about what is still hardware-gated.

### The problem with “just add MFA”

Cabin MFA has three failure modes that phone MFA papers over:

1. **Present attackers.** Replay and presentation attacks are close-range by default.
2. **Unavailable channels.** OTP depends on the network; the car often does not.
3. **Blended signals.** Teams quietly let GPS, amount, or “risky drive style” inflate a biometric match. That makes compliance reviews impossible and trains the model to launder risk into identity.

We wanted the opposite: **identity and transaction risk stay on separate rails**, and a deterministic policy joins them where auditors can read the rules.

### Separation: Trust ≠ Risk ≠ Confidence

| Score | Question | Inputs (examples) |
|-------|----------|-------------------|
| **Trust** | Is this the enrolled driver? | Voice, face, fingerprint — quality-weighted |
| **Risk** | How unusual is this transaction? | Amount z-score, novel payee, distance from home, speed, CAN behaviour |
| **Confidence** | Can we trust *our* scores this time? | SNR/blur, OOD flags, modality disagreement |

These three feed a **Policy Engine** (`policy.yaml` / env overrides) — not another neural net. Changing “accept bar for face” does not require retraining ECAPA or MobileFaceNet.

Hard invariants we enforce in code and docs:

- Risk signals **never** raise Trust.
- Missing or crashed modalities **fail closed** — they do not silent-ACCEPT.
- Cellular OTP / offline PIN are **step-up fallbacks**, not a finger substitute mid-ladder.

Full write-up: [Security assumptions](https://github.com/couder-04/Drive_auth_edge/blob/main/docs/security-assumptions.md).

### The biometric ladder (UX without lying about security)

Identity acceptance is a **Voice → Face → Finger** ladder:

- Strong voice → early-stop **ACCEPT** (fast path for micro-payments).
- Weak voice → escalate to face; weak face → finger.
- Hard Risk ceiling / fraud lock → **REJECT** regardless of biometrics.
- Ambiguous fused trust → **STEP_UP** (guest PIN / exhausted path).

That early-stop is a UX win **only if** the ship bars are honest. Our Sprint 6 ablations quantify the trade: under balanced voice bars, staged early-stop lowers FRR vs force-full MFA; under conservative shipping bars we prefer **FAR≈0** and accept high FRR until finger hardware and face calibration catch up. Security floor first — then tune UX.

See [`phases/phase6.md`](https://github.com/couder-04/Drive_auth_edge/blob/main/phases/phase6.md) for the Sprint 6 table (EER/ROC, PAD APCER/BPCER, Risk AUC, Mac/Thor latency, early-stop vs security-floor ablation).

### What’s on the edge today

| Component | Status (July 2026) |
|-----------|-------------------|
| Voice | ECAPA-TDNN pretrained + enrolled; Stage-2 calibrator |
| Face | MobileFaceNet ONNX + PAD + calibrator (own-face enroll) |
| Finger | Mock / ManualScores until sensor SDK |
| Behavioural | LSTM ONNX on **synth** CAN — re-bake on real recorder dumps |
| Risk | LightGBM → ONNX, val AUC ≈ 0.9955 on 50k synthetic txns |
| Trust fusion | Stage-1 static weights; Stage-2 logistic → ONNX |
| Latency | Mac Phase 2a micro p95 ≈ 38 ms; Thor CUDA micro/high p95 ≈ 7.7 / 9.2 ms |
| Tests | 155+ including timing side-channel pad and OOD-refresh gating |

Models run via ONNX Runtime. Thor uses a CUDA EP build; the decision path stays deterministic after scores are produced.

### Security we actually designed for

Threats we treat as in-scope: unauthorized cabin user, replay/presentation, slow OOD poisoning of enrollment stats, risky-but-genuine sessions, timing observers inferring early-stop vs full ladder, missing sensors.

Responses worth calling out:

- **Fail-closed** quality / OOD / matcher faults.
- **OOD refresh gated** on strong auth (so drift cannot quietly rewrite baselines).
- **Optional constant-time pad** on escalation wall-clock (`DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS`) when observers are in scope.
- **Audit log** stores decision metadata and scores — not raw biometric templates.

Out of scope for this release (platform responsibility): stolen phone OTP factors, compromised host OS / model keys, network MITM on the in-vehicle IPC channel.

### What we refuse to claim (please quote this)

Public demos are easy to oversell. We document non-claims up front:

- Finger metrics with proxy scores are **not** production FAR/FRR.
- Behavioural AUC on synth CAN is **pipeline evidence**, not fleet biometric quality.
- Risk AUC is on the **synthetic 50k** split — retrain before citing live card fraud.
- Shipping policy bars can yield **FRR=1** on current eval sets by design (reject until finger/real calibration improves UX).
- Dashboard ManualScores are for integration demos — **not** a security control.

If a benchmark disappears when you remove the proxy finger, it was never a system claim.

### Lessons that survived contact with the edge

1. **Separate scores beat a clever fusion head** when compliance has to change rules weekly.
2. **Early-stop is an ablation, not a slogan** — publish FAR/FRR vs the security floor.
3. **PAD and calibrators matter more than swapping another backbone** once you have a decent embedding model.
4. **Own-face enroll beats celebrity stills** before you touch thresholds.
5. **Write the security assumptions before the LinkedIn post** — it keeps the marketing honest.

### Try it

```bash
git clone https://github.com/couder-04/Drive_auth_edge.git
cd Drive_auth_edge
# Python 3.11+ — see README for setup
driveauth-dashboard
```

Presets in the dashboard: micro payment → ACCEPT; low voice → face ACCEPT; low biometrics → REJECT.

We’re aiming at IV/ITSC for the automotive systems story; CCS/NDSS-style venues only if the paper leads with timing, OOD-drift, and the security-floor analysis.

If you work on cabin UX, payment risk, or edge biometrics — open an issue or reach out. The interesting problems left are mostly **hardware and honesty**: real finger, real CAN, live GPS, and fleet-tuned bars that still fail closed.

---

## 3. Optional LinkedIn short teaser (announce-only)

```
Shipped DriveAuth Edge — offline Trust/Risk-separated auth for in-car payments.

Voice → Face → Finger ladder · deterministic policy · Thor CUDA p95 < 10 ms ·
security assumptions published (what we don’t claim is as important as what we do).

Repo + demo GIF:
https://github.com/couder-04/Drive_auth_edge

Thread with architecture in comments ↓
```

---

## 4. Publish checklist

- [ ] Attach `docs/demo.gif` on LinkedIn
- [ ] Medium: embed GIF; link README, security-assumptions, phase6
- [ ] First LinkedIn comment = Medium URL + “Trust never uses GPS/amount”
- [ ] Do not paste Stage-6 FRR=1 without the “security-first bars” sentence
- [ ] After publish: paste URLs below and tick TODO Phase 7

**Published URLs**

| Venue | URL | Date |
|-------|-----|------|
| LinkedIn | | |
| Medium | | |
