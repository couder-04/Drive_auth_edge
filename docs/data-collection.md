# Pilot fleet data collection

How to produce a **first real** DriveAuth dataset that drops into the existing
trainers. This pipeline does not fabricate driving telemetry — it only makes
logs from real vehicles interchangeable with the synthetic schemas.

Companion: [`hardware/can_logger.py`](../hardware/can_logger.py) ·
[`scripts/train_risk_gbt.py`](../scripts/train_risk_gbt.py) ·
[`scripts/train_behavioral_bakeoff.py`](../scripts/train_behavioral_bakeoff.py) ·
[`docs/security-assumptions.md`](security-assumptions.md)

---

## What to run on each vehicle

```bash
pip install -e ".[hardware]"   # includes python-can when declared
# On the head unit (SocketCAN):
python -m hardware.can_logger \
  --out /var/driveauth/fleet/vehicle_03 \
  --driver-id drv_0003 \
  --channel can0 \
  --home-lat 12.97 --home-lon 77.59
```

Outputs under `--out`:

| Path | Schema | Trainer |
|------|--------|---------|
| `transaction/txns_real.csv` | Same columns as `generate_risk_txns.py` | `train_risk_gbt.py --real-data-dir` |
| `behavioral/genuine/can_XXXX.csv` | `BEHAVIORAL_FEATURE_KEYS` | `train_behavioral_bakeoff.py --real-data-dir` |
| `can_frames.csv` | Raw frames + GPS (debug) | — |

Payment fields (`amount`, `beneficiary`, `label`) are **not** on the CAN bus.
Call `CanLogger.record_txn_snapshot(...)` from the payment path when a txn
completes, or label offline before training.

Replace the default byte→feature decoder with a vehicle-specific DBC mapping
before treating behavioral windows as production-grade.

---

## Pilot sizing (rough guidance)

| Goal | Vehicles (N) | Duration (M) | Rough yield |
|------|--------------|--------------|-------------|
| Smoke / schema check | 1–2 | days | dozens of windows; not for AUC claims |
| First usable risk train/eval split | ≥5 | 2–4 weeks | ≥5k labelled txns with class balance; hold out ≥1 vehicle |
| Behavioral bake-off that can beat synth | ≥8 | 4–8 weeks | ≥200 genuine + ≥50 attack/spoof windows per fold |

Rules of thumb:

- Keep a **vehicle-held-out** eval set (never train on the same VIN you publish).
- Prefer more weeks on fewer cars over one day on many — within-driver variance matters.
- Until `n_real > 0` in the training report, treat AUC / bake-off winners as **synthetic-only** (gap still open in security-assumptions).

---

## Train with real + synthetic

```bash
# Risk head — real rows weighted higher (default --real-weight 3)
python scripts/train_risk_gbt.py \
  --csv data/driver1/transaction/txns.csv \
  --real-data-dir /var/driveauth/fleet \
  --out driveauth_store/risk_gbt.onnx

# Behavioral bake-off — real windows oversampled (--real-repeat 3)
python scripts/train_behavioral_bakeoff.py \
  --data data/driver1/behavioral \
  --real-data-dir /var/driveauth/fleet/vehicle_03/behavioral \
  --store driveauth_store \
  --driver-id driver1
```

Both scripts print a clear **WARNING** banner when the run used zero real samples.
