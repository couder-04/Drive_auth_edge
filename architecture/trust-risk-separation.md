# Trust / Risk / Confidence

## Trust Score (0–1)

**Question:** Is the person initiating this action the enrolled driver?

**Inputs:** voice cosine similarity, face embedding match, fingerprint match — weighted by live capture quality.

**Never uses:** GPS, speed, transaction amount, driving style, time of day.

```python
# fusion.py — TrustFusion.fuse()
trust, weights = trust_fusion.fuse(voice_r, face_r, finger_r)
```

Static default weights: voice 30%, face 40%, finger 30%. Override via
`driveauth/policy.yaml` placeholders (`DRIVEAUTH_TRUST_W_*`) or `DynamicOrchestrator`
(PolicyMLP ONNX).

## Risk Score (0–1)

**Question:** How unusual/risky is this transaction independent of identity?

**Inputs:**

| Signal | Example |
|--------|---------|
| `amount_z` | Far above user's historical mean |
| `beneficiary_novel` | First-time payee |
| `dist_from_home` | 40 km from home base |
| `out_of_zone` | Outside trusted geofence |
| `moving_fast` | Payment while driving 90 km/h |
| `behavior_anomaly` | Driving style doesn't match enrolled profile |

Runs on **CPU** (`risk_gbt.onnx` if trained, else transparent additive fallback).

## Confidence Score (0–1)

**Question:** Should we trust our own biometric scores on this capture?

Penalizes:

- Modality disagreement (voice says yes, face says no)
- Low SNR / clipping / blur
- OOD embeddings (mask, replay, sensor spoof)
- Hardware fault flags

Low confidence → Policy routes to **STEP_UP** even if Trust looks high.

## Policy bands

Defaults live in [`driveauth/policy.yaml`](../driveauth/policy.yaml) as
`${ENV:default}` placeholders:

| Variable | Default | Meaning |
|----------|---------|---------|
| `DRIVEAUTH_RISK_APPROVE` | 0.35 | Risk ≤ this → low-risk band |
| `DRIVEAUTH_RISK_REJECT` | 0.80 | Risk ≥ this → hard reject |
| `DRIVEAUTH_TRUST_REJECT` | 0.55 | Trust below → reject |
| `DRIVEAUTH_CONF_FLOOR` | 0.55 | Confidence below → step-up |

## Tiers

| Tier | Trigger | Behaviour |
|------|---------|-----------|
| `micro` | amount ≤ ₹200, known beneficiary | Single strong modality may suffice |
| `standard` | default | 2-of-3 modalities, ambiguous → OTP |
| `high_value` | amount ≥ ₹50k or unknown beneficiary | Mandatory OTP step-up |
| `guest` | guest profile | PIN/card only — biometrics skipped |
