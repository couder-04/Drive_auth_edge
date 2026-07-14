# Integration guide

## Nova ↔ DriveAuth: transaction pipeline contract

### Inputs Nova must supply

| Source | What to pass | API |
|--------|----------------|-----|
| STT mic | Float32 mono audio ~16 kHz | `authenticate(audio_np=…)` or `intercept(transcript, audio_np, …)` |
| Intent / LLM | Payment fields | `amount`, `beneficiary`, `action`, `currency`, `channel`, `beneficiary_known`, `is_guest` |
| Utterance only | Raw transcript | `intercept()` — DriveAuth parses amount/beneficiary via `intent.py` |
| GPS / telematics | Live fix | `update_vehicle_context(gps_lat=, gps_lon=, gps_accuracy_m=, speed_kmh=, ignition_on=, is_tunnel=…)` |
| CAN / IMU (optional) | Driving windows | `update_behavioral({steering_angle_deg, steering_rate_dps, throttle_pct, brake_pedal_pct, longitudinal_accel_g, lateral_accel_g, yaw_rate_dps, vehicle_speed_kmh})` |
| Face camera | BGR frame | `FaceMatcher.inject_bgr` / live capture (or mock score until HW) |
| Fingerprint | Match score `[0,1]` | Same `ModalityResult` from sensor SDK module (dashboard sliders until then) |

Until sensors exist, the **dashboard “Manual stand-ins” column** sets the same fields Nova will fill automatically later.

### Outputs DriveAuth returns

| Field | Meaning |
|-------|---------|
| `decision` | `ACCEPT` \| `REJECT` from Voice→Face→Finger ladder (`STEP_UP_REQUIRED` only for guest PIN) |
| `legacy_decision` | Nova-compatible: `pass` / `step_up` / `deny` |
| `trust_score` / `risk_score` / `confidence_score` | Reporting triad (Accept/Reject is ladder-driven) |
| `tier` | `micro` \| `standard` \| `high_value` \| `guest` |
| `policy_rule` | Which policy band fired |
| `fraud_state` | Fraud ladder state |
| `step_up_method` | OTP / PIN path when stepping up |
| `explanations` | Human-readable reasons |
| `modality_scores` | Per-modality probes used |
| `ood_flags` | OOD hits per modality |
| `intercept()` return | `"pass"` \| `"step_up"` \| `"deny"` for STT queue routing |

---

## Standalone Python

```bash
pip install -e /path/to/driveauth-edge
```

```python
from driveauth import DriveAuth

auth = DriveAuth.load(
    store_dir="/var/driveauth/store",
    enroll_dir="/var/driveauth/l3_enroll",
    driver_id="driver1",
)
auth.update_vehicle_context(
    gps_lat=12.97,
    gps_lon=77.59,
    gps_accuracy_m=8.0,
    speed_kmh=0.0,
    ignition_on=True,
)
result = auth.authenticate(audio_np=audio, amount=500.0, beneficiary="Mom", beneficiary_known=True)
print(result.decision, result.legacy_decision, result.trust_score, result.risk_score)
```

## Nova AI `pipeline_mp` migration

1. Install `driveauth-edge` editable or add to `PYTHONPATH`.
2. In `stt_*_worker.py` and `llm_worker.py`:

```python
# Before
from driveauth.gate import DriveAuthGate

# After
from driveauth import DriveAuth as DriveAuthGate
```

3. Remove or keep `nova/backend/pipeline_mp/driveauth/` as a thin shim:

```python
# pipeline_mp/driveauth/__init__.py (optional shim)
from driveauth import DriveAuth as DriveAuthGate
```

4. Point enrollment at existing L-3 data:

```bash
export DRIVEAUTH_ENROLL_DIR=nova/backend/nova-l7/L-3
export DRIVEAUTH_STORE_DIR=models/biometric_store
```

5. From the telematics thread (when GPS HW is ready), call `update_vehicle_context(...)` **before** each payment auth.

## STT intercept contract

`DriveAuth.intercept(transcript, audio_np, ws_out_queue, llm_in_queue)` returns:

| Return | Meaning |
|--------|---------|
| `"pass"` | Dispatched to `llm_in_queue` |
| `"step_up"` | OTP or PIN fallback in progress |
| `"deny"` | Blocked — TTS + security alert sent |

## Vehicle context feed

Call from CAN/telematics thread:

```python
auth.update_behavioral({
    "steering_angle_deg": 4.2,
    "steering_rate_dps": 8.0,
    "throttle_pct": 28.0,
    "brake_pedal_pct": 0.0,
    "longitudinal_accel_g": 0.05,
    "lateral_accel_g": 0.02,
    "yaw_rate_dps": 3.5,
    "vehicle_speed_kmh": 65.0,
})
auth.update_vehicle_context(
    gps_lat=12.97,
    gps_lon=77.59,
    gps_accuracy_m=8.0,
    speed_kmh=65.0,
    ignition_on=True,
)
```

Dashboard can set the same fields manually until Nova wires sensors.

## Training optional models

| Model | Script | Output |
|-------|--------|--------|
| PolicyMLP (trust weights) | `train_orchestrator.py` in Nova repo | `orchestrator_mlp.onnx` |
| Risk GBT | `scripts/train_risk_gbt.py` | `risk_gbt.onnx` |

Place ONNX files in `DRIVEAUTH_STORE_DIR`.
