# API reference — `driveauth.api.DriveAuth`

Public surface for embedding DriveAuth Edge in Nova or a standalone product.
Integration narrative lives in [integration.md](integration.md); this page is
the method/field contract.

```python
from driveauth import DriveAuth, DriveAuthResult, Decision
```

`DriveAuthGate` is an alias of `DriveAuth` for Nova drop-in replacement.

---

## Factory

### `DriveAuth.load(...)` → `DriveAuth`

| Arg | Type | Default | Meaning |
|-----|------|---------|---------|
| `store_dir` | `str \| None` | `DRIVEAUTH_STORE_DIR` or `./driveauth_store` | Templates, OOD baselines, audit, contacts |
| `enroll_dir` | `str \| None` | — | Optional enrollment tree |
| `driver_id` | `str` | `"driver1"` | Active enrolled driver |
| `enabled` | `bool` | `True` | When False, `intercept()` always passes |
| `use_mock_matchers` | `bool` | `False` | Force mock voice/face/finger (also `DRIVEAUTH_USE_MOCK=1`) |

Side effects on load: optional signed-manifest integrity check, matcher
selection (real ONNX/SpeechBrain/Hailo vs mock), ladder Bluetooth OTP attach,
IR liveness attach, optional `DRIVEAUTH_MANUAL_SCORES`.

### `DriveAuth.load_gate(**kwargs)` → `DriveAuth`

Alias of `load()` for Nova `DriveAuthGate.load()` compatibility.

---

## Session & context

### `new_session()` → `str`

Rotates `session_id` (hex UUID) and invalidates the decision cache.

### `session_id` (property) → `str`

Current session id stamped onto results.

### `invalidate_cache()` → `None`

Drops the cached ACCEPT used by `require_auth`.

### `update_behavioral(sensor: dict[str, float])` → `None`

Feeds the behavioral monitor. Recognized telematics keys also update risk
context: `vehicle_speed_kmh`, `ignition_on`.

### `update_vehicle_context(**kwargs)` → `None`

Sets fields on the live `RiskContext` when the attribute exists (`gps_lat`,
`gps_lon`, `gps_accuracy_m`, `speed_kmh`, `ignition_on`, `is_tunnel`,
`dist_from_home_km`, `in_trusted_zone`, …).

### `mark_not_mine()` → `None`

Driver-confirmed fraud signal — advances the fraud state machine and bumps
the cache epoch.

---

## Decisions

### `authenticate(...)` → `DriveAuthResult`

Primary gate. Runs quality → ladder probes → trust/risk/confidence → policy.

| Arg | Type | Default | Meaning |
|-----|------|---------|---------|
| `audio_np` | `np.ndarray \| None` | required kw | Mono float32 voice clip (or None if voice not expected) |
| `tier_hint` | `str` | `"payment"` | Hint for tier classification |
| `amount` | `float` | `0.0` | Transaction amount |
| `beneficiary` | `str` | `""` | Payee name |
| `action` | `str` | `""` | Free-form action label |
| `currency` | `str` | `"INR"` | Currency code |
| `channel` | `str` | `"voice"` | `voice` / `llm_tool` / … |
| `beneficiary_known` | `bool` | `False` | Whether payee is in allow-list |
| `is_guest` | `bool` | `False` | Guest mode (stricter / no ladder accept) |
| `is_payment` | `bool` | `True` | Stamped onto result |
| `voice_expected` | `bool \| None` | auto | Override voice probe expectation |
| `face_expected` | `bool \| None` | auto | Override face probe expectation |
| `session_id` | `str \| None` | current | Override session stamp |
| `audit` | `bool` | `True` | Write audit JSONL + profile updates |
| `event` | `str` | `"authenticate"` | Audit event name |
| `transcript` | `str` | `""` | Optional STT text for audit |

### `require_auth(...)` → `DriveAuthResult`

LLM tool-boundary re-check. May reuse a fresh cached ACCEPT within
`DECISION_CACHE_TTL_S` when tier does not increase and fraud/profile epochs
are unchanged. Calls `authenticate(audio_np=None, voice_expected=False, …)`
on cache miss.

### `intercept(transcript, audio_np, ws_out_queue, llm_in_queue)` → `str`

Nova STT-worker hook. Returns legacy `"pass"` | `"step_up"` | `"deny"`.
Non-payment utterances bypass the payment path entirely.

---

## `DriveAuthResult` fields

| Field | Type | Meaning |
|-------|------|---------|
| `trust_score` | `float` | Identity trust ∈ [0,1] (voice/face/finger fusion) |
| `risk_score` | `float` | Transaction risk ∈ [0,1] |
| `confidence_score` | `float` | Confidence in the scores (quality/OOD/agreement) |
| `decision` | `Decision` | `ACCEPT` \| `STEP_UP_REQUIRED` \| `REJECT` |
| `tier` | `str` | `micro` / `standard` / `high_value` / `guest` / … |
| `explanations` | `list[str]` | Machine-readable reason codes (ladder bars, OOD, …) |
| `step_up_method` | `str \| None` | Payment step-up channel (e.g. `otp_mobile`) |
| `step_up_fallback` | `str \| None` | Offline fallback label when OTP unavailable |
| `stage3_method` | `str \| None` | Identity-ladder stage-3: `"finger"` \| `"otp_bluetooth"` \| `None` |
| `policy_rule` | `str` | Fired policy rule id |
| `fraud_state` | `str` | Fraud ladder state name |
| `modality_scores` | `dict` | Per-modality `score` / `conf` / `q` / `available` / `latency_ms` + `effective_weights` |
| `active_thresholds` | `dict[str, float]` | Thresholds used for this decision |
| `ood_flags` | `dict[str, bool]` | Per-modality OOD flags |
| `is_payment` | `bool` | Payment vs non-payment path |
| `amount` / `currency` / `beneficiary` / `action` / `channel` | — | Echo of request context |
| `session_id` | `str` | Session stamp |
| `driver_id` | `str` | Enrolled driver id |

Properties:

- `score` → alias of `trust_score`
- `legacy_decision` → `"pass"` | `"step_up"` | `"deny"` (Nova string form)

### `Decision` enum

| Value | Legacy |
|-------|--------|
| `ACCEPT` | `pass` |
| `STEP_UP_REQUIRED` | `step_up` |
| `REJECT` | `deny` |

### `ModalityResult` (matcher contract)

| Field | Meaning |
|-------|---------|
| `score` | Match ∈ [0,1] or `None` |
| `confident` | Matcher believes the score |
| `latency_ms` | Inference / capture latency |
| `quality` | Quality gate scalar |
| `ood` | Out-of-distribution flag |
| `embedding` | Optional vector (never sent to fleet telemetry) |
| `available` | `False` when sensor/model missing (fail-closed) — not merely a low score |

---

## Minimal example

```python
import numpy as np
from driveauth import DriveAuth, Decision

auth = DriveAuth.load(store_dir="./store", use_mock_matchers=True)
auth.update_vehicle_context(gps_lat=12.97, gps_lon=77.59, speed_kmh=0.0)

audio = np.zeros(16_000, dtype=np.float32)  # replace with real mic buffer
result = auth.authenticate(
    audio_np=audio,
    amount=150.0,
    beneficiary="Mom",
    beneficiary_known=True,
)
print(result.decision, result.trust_score, result.risk_score)
assert result.decision in Decision
```
