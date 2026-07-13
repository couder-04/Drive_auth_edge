# Integration guide

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
auth.update_vehicle_context(speed_kmh=0.0, in_trusted_zone=True)
result = auth.authenticate(audio_np=audio, amount=500.0)
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
    "vehicle_speed_kmh": 65.0,
    "steering_torque_nm": 1.2,
    "ignition_on": 1.0,
})
auth.update_vehicle_context(
    gps_lat=12.97, gps_lon=77.59,
    in_trusted_zone=True,
    dist_from_home_km=5.0,
)
```

## Training optional models

| Model | Script | Output |
|-------|--------|--------|
| PolicyMLP (trust weights) | `train_orchestrator.py` in Nova repo | `orchestrator_mlp.onnx` |
| Risk GBT | Your own training pipeline | `risk_gbt.onnx` |

Place ONNX files in `DRIVEAUTH_STORE_DIR`.
