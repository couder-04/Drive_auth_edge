# Architecture overview

## Pipeline

```text
Sensor capture
    │
    ▼
QualityGate (§8a.5) ──reject bad captures──▶ skip matcher
    │
    ▼
Matchers (parallel)
    ├── VoiceMatcher   (ECAPA-TDNN)
    ├── FaceMatcher    (MobileFaceNet ONNX)
    └── FingerMatcher  (FingerNet-lite ONNX)
    │
    ├──▶ TrustFusion        → Trust Score   [biometrics ONLY]
    ├──▶ RiskModel          → Risk Score    [GPS/CAN/amount/behaviour]
    ├──▶ OODDetector        ─┐
    └──▶ QualityFlags         ┼▶ ConfidenceScorer
                              │
    ▼
PolicyEngine (deterministic tiers: micro / standard / high_value / guest)
    │
    ▼
Decision: ACCEPT | STEP_UP_REQUIRED | REJECT
    │
    ├── FraudStateMachine adjusts rigor over time
    ├── STEP_UP → OTP (cellular) → offline PIN+biometric fallback
    └── AuditLog (metadata only — no raw biometrics)
```

## Module map

| Module | Responsibility |
|--------|----------------|
| `api.py` | Public `DriveAuth` class, Nova `intercept()` compatibility |
| `decision_engine.py` | Wires quality → matchers → scores → policy |
| `fusion.py` | Trust + Confidence |
| `risk_model.py` | Transaction/vehicle context risk (CPU) |
| `policy_engine.py` | Human-auditable rules |
| `fraud_state.py` | Normal → Elevated → Heightened → Locked ladder |
| `matchers/` | Pluggable biometric backends |
| `orchestrator.py` | Optional dynamic trust weights (PolicyMLP) |

## Trust/Risk separation (the key fix)

Before DriveAuth Edge, behavioural driving scores and GPS context could inflate the **Trust** score — conflating *who you are* with *where/how you're driving*.

After: behaviour and location feed **Risk only**. Trust is biometric-only. A driver in an unfamiliar city at night gets higher **Risk** (more scrutiny) without their voice match score being artificially lowered or raised.
