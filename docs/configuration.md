# Configuration

Thresholds live in [`driveauth/policy.yaml`](../driveauth/policy.yaml) — the single
source of truth across the repo. Every value is a `${ENV_VAR:default}` placeholder:
set the env var to override, or leave unset to use the default after the colon.

`DRIVEAUTH_*` is preferred; `NOVA_*` aliases still work for Nova AI drop-in.
Point `DRIVEAUTH_POLICY_FILE` at another YAML to swap the whole pack (fleet/OEM overlays).

## Store layout

```
driveauth_store/
├── .bio_key                 # Fernet key for encrypted templates
├── faces/{driver_id}.enc
├── fingers/{driver_id}.enc
├── pins/{driver_id}.enc
├── behavioral/{driver_id}.enc
├── contacts/{driver_id}.mobile
├── ood_stats/
│   ├── voice_{driver_id}.npz
│   ├── face_{driver_id}.npz
│   └── finger_{driver_id}.npz
├── fraud/ladder.json
├── audit/driveauth_events.jsonl
├── risk_gbt.onnx            # optional trained risk model
└── orchestrator_mlp.onnx    # optional dynamic trust weights
```

## Policy file

```bash
# Use the packaged defaults (driveauth/policy.yaml)
# Or overlay:
export DRIVEAUTH_POLICY_FILE=/etc/driveauth/policy.yaml

# Or override individual placeholders:
export DRIVEAUTH_RISK_APPROVE=0.30
export DRIVEAUTH_TRUST_REJECT=0.50
export DRIVEAUTH_CONF_FLOOR=0.60
```

Placeholder form in YAML:

```yaml
risk:
  approve: ${DRIVEAUTH_RISK_APPROVE:0.35}
  reject: ${DRIVEAUTH_RISK_REJECT:0.80}
```

## Key variables

```bash
DRIVEAUTH_STORE_DIR=./driveauth_store
DRIVEAUTH_ENROLL_DIR=./enroll          # voiceprints (L-3 compatible)
DRIVEAUTH_USE_MOCK=1                   # mock matchers for dev/test
DRIVEAUTH_FINGERPRINT_AVAILABLE=0      # trim without fingerprint sensor
DRIVEAUTH_POLICY_FILE=                 # optional alternate policy.yaml

# Risk / trust thresholds (also in policy.yaml)
DRIVEAUTH_RISK_APPROVE=0.35
DRIVEAUTH_RISK_REJECT=0.80
DRIVEAUTH_TRUST_REJECT=0.55
DRIVEAUTH_CONF_FLOOR=0.55

# OTP step-up (optional — offline fallback if unset)
DRIVEAUTH_OTP_PROVIDER_URL=https://provider.example/send-otp
DRIVEAUTH_DRIVER_MOBILE=+91XXXXXXXXXX

# Fraud ladder
DRIVEAUTH_FRAUD_LADDER_DECAY_HOURS=24
```

See `driveauth/policy.yaml` for the full set (quality gates, OOD, fraud rigor,
bootstrap, escalation, confidence weights, …).

## Hardware

| Matcher | Env | Default |
|---------|-----|---------|
| IR camera index | `DRIVEAUTH_IR_CAMERA_INDEX` | 0 |
| Fingerprint socket | `DRIVEAUTH_FINGER_SOCKET` | `/tmp/driveauth_finger.sock` |
