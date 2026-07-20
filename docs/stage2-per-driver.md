# Stage-2 per-driver migration guide

## Why

Stage-2 bio heads (`face_pad`, `face_calibrator`, `voice_calibrator`) used to live
once per store root. Retraining for driver7 overwrote the heads used by driver1
(and every other enrollee). That is a correctness bug, not a threshold issue.

## New layout

Encrypted templates stay as flat files. Stage-2 bio heads are per driver:

```
driveauth_store/
  faces/
    driver1.enc                 # template (unchanged)
    driver1/
      face_pad.onnx
      face_pad.json
      face_calibrator.onnx
      face_calibrator.json
    driver7.enc
    driver7/
      …
  voices/
    driver1.enc
    driver1/
      voice_calibrator.onnx
      voice_calibrator.json
  risk_gbt.onnx                 # still store-global
  trust_fusion.onnx             # still store-global
  face_pad.onnx                 # LEGACY shared (optional; preserved by migration)
```

## Loading order

For each bio head:

1. `faces/{id}/…` or `voices/{id}/…` (per-driver)
2. store-root legacy file (WARNING logged — never silent)
3. missing → matcher runs without that head

## Migrate an existing store

```bash
python scripts/migrate_stage2_per_driver.py --store driveauth_store_phase2a
# idempotent — safe to re-run
python scripts/migrate_stage2_per_driver.py --store driveauth_store_phase2a
```

Migration **copies** shared heads into every enrolled driver directory and
**does not delete** the originals. After migrate, **retrain each driver** so
heads are not still a shared snapshot:

```bash
python scripts/train_face_pad.py --store driveauth_store_phase2a \
  --data data/driver1 --driver-id driver1 --exclude-fallback-crops
python scripts/train_face_calibrator.py --store … --data data/driver1 --driver-id driver1
python scripts/train_voice_calibrator.py --store … --data data/driver1 --driver-id driver1

# repeat for driver7, …
```

`--exclude-fallback-crops` drops Haar-miss center-crop samples that pollute PAD
features (especially `attack_side`). If LOO AUC ≤ 0.55 after retrain, the
matcher **disables** the PAD gate and documents it in `face_pad.json`.

## Compatibility

Old stores with only store-root heads still load (with a loud WARNING). New
trainers never write to store root. Purge removes `faces/{id}/` and
`voices/{id}/` with the driver.

### Migrated copy ≠ independent retrain

Migration stamps `migrated_from` / `migrated_at` on the per-driver JSON.
Dashboard / integrity report `mode=per_driver_migrated` and `needs_retrain=true`
until you retrain that driver (retrain clears the migration stamp by rewriting
the JSON). Drivers without genuine/attack labeled sets cannot be honestly
retrained — leave them migrated and treat PAD/calibrators as provisional.

Templates use encrypted `faces/{id}.enc` / `voices/{id}.enc` (not
`embeddings.bin`).

## Verify

```bash
python scripts/bootstrap.py --check-only --store driveauth_store_phase2a
python scripts/overfit_audit_stage2.py --store driveauth_store_phase2a --driver-id driver1
pytest tests/test_stage2_per_driver.py tests/test_stage2_fusion.py -q
```
