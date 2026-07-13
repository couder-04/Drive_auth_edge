# Phase 2b — risk train + bio calibration

Date: 2026-07-13

## 1. Risk GBT → `risk_gbt.onnx`

```bash
pip install lightgbm onnxmltools onnx skl2onnx scikit-learn
python scripts/train_risk_gbt.py \
  --csv data/driver1/transaction/txns.csv \
  --out driveauth_store_phase2a/risk_gbt.onnx
```

| Item | Result |
|------|--------|
| Backend | LightGBM |
| Rows | 30 (24 legit / 6 suspicious) |
| Train acc @0.5 | 1.0 *(tiny set — expect overfit; retrain with more txns)* |
| Mean risk legit | ~0.001 |
| Mean risk suspicious | ~0.999 |
| Artifact | `driveauth_store_phase2a/risk_gbt.onnx` (+ `.json`) |

`RiskModel.load` picks this up automatically from the store. ONNX probability parsing updated for `(label, probabilities)` outputs.

## 2. Voice / face threshold calibration

```bash
python scripts/calibrate_bio_thresholds.py --store ./driveauth_store_phase2a --apply
```

| Split | Voice mean | Face mean |
|-------|------------|-----------|
| Genuine | 0.70 | 0.63 |
| Attack | 0.23 | 0.30 |

Separation is strong for **voice**, moderate for **face** (some genuine/attack overlap).

**`policy.yaml` defaults updated (conservative):**

| Key | Old | New |
|-----|-----|-----|
| accept_micro | 0.75 | **0.70** |
| accept_standard | 0.82 | **0.78** |
| accept_high | 0.88 | **0.85** |
| reject | 0.55 | **0.48** |

More aggressive percentile suggestions: `phases/phase2b_suggested.env` / `phases/phase2b_calibration.json`.

## 3. Optional / HW-gated (not done this session)

| Item | Status |
|------|--------|
| Phase 2a real-model latency on Thor | Deferred — needs SSH + `pip install ".[voice,face]"` on board |
| Voice anti-spoof / face PAD | Deferred — need attack models + more data |
| Finger matcher | Deferred — no sensor / `fingernet_lite_int8.onnx` |

## Verify

```bash
# risk ONNX loaded
python -c "from driveauth.risk_model import RiskModel; print(RiskModel.load('driveauth_store_phase2a')._session is not None)"

# bio ACCEPT still
python scripts/phase2a_demo.py --store ./driveauth_store_phase2a \
  --face-image data/driver1/face/enroll/enroll_01.jpg
```
