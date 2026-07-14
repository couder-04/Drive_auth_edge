# Phase 3 — Dataset collection (how to)

Start **now** on Mac. Thor is not required. Goal: enough labeled samples that Phase **2b** can fine-tune (enrollment + genuine + ≥1 attack class per modality).

## Minimum to unlock Phase 2b

Per enrolled driver (start with **you** as `driver1`):


| Modality    | Enroll            | Genuine               | Attack (pick ≥1)                          |
| ----------- | ----------------- | --------------------- | ----------------------------------------- |
| Voice       | 5–10 clips        | 20+                   | replay **or** silent **or** other-speaker |
| Face        | 5–10 frames       | 20+                   | blur / side-pose / photo-of-screen        |
| Finger      | skip if no sensor | —                     | —                                         |
| Transaction | —                 | 30+ synthetic rows OK | a few “fraud-like” rows                   |


Full roadmap wishlist (highway, IR, wet finger, …) comes **after** this minimum.

## Folder layout

```text
data/
├── README.md                 # this file
├── manifest.csv              # one row per file (auto-append helpers below)
└── driver1/
    ├── voice/
    │   ├── enroll/
    │   ├── genuine/
    │   ├── attack_replay/
    │   ├── attack_silent/
    │   ├── attack_other_speaker/
    │   └── noisy/
    ├── face/
    │   ├── enroll/
    │   ├── genuine/
    │   ├── attack_blur/
    │   ├── attack_side/
    │   └── attack_replay_screen/
    ├── finger/               # optional
    ├── behavioral/           # CAN CSV later
    └── transaction/          # CSV of amount/beneficiary/time/gps/label
```

Do **not** commit raw biometrics to git. Keep `data/` local (already gitignored if you add it) or on encrypted disk.

## Capture on Mac



### Voice (16 kHz mono WAV — matches the pipeline)

```bash
# one enrollment utterance (~2–3 s). Repeat 5–10 times with different phrases.
ffmpeg -f avfoundation -i ":default" -ar 16000 -ac 1 -t 3 \
  data/driver1/voice/enroll/enroll_01.wav
```

Phrases to rotate: `"pay Mom fifty"`, `"transfer two hundred to Raj"`, `"open navigation"` (non-pay), count 1–10.


| Class                   | How                                                             |
| ----------------------- | --------------------------------------------------------------- |
| `genuine/`              | Same speaker, same mic, normal cabin-ish room                   |
| `noisy/`                | Fan / traffic / music in background                             |
| `attack_silent/`        | Record 3 s of silence / near-silence                            |
| `attack_replay/`        | Play an enroll WAV from phone speakers → re-record with Mac mic |
| `attack_other_speaker/` | Someone else reads the same phrases                             |




### Face (still frames)

```bash
# grab from Continuity Camera / FaceTime camera
ffmpeg -f avfoundation -framerate 30 -i "0" -frames:v 1 \
  data/driver1/face/enroll/enroll_01.jpg
```

Or Photos / Photo Booth → export JPG into the right folder.


| Class                   | How                                      |
| ----------------------- | ---------------------------------------- |
| `enroll/`               | Frontal, good light, face large in frame |
| `genuine/`              | Same, slight pose/light variation        |
| `attack_blur/`          | Motion blur or soft focus                |
| `attack_side/`          | Clear profile / >45° yaw                 |
| `attack_replay_screen/` | Photo of your face on another screen     |




### Transaction labels (no hardware)

Create `data/driver1/transaction/txns.csv`. The full schema consumed by
`scripts/train_risk_gbt.py` is:

```csv
amount,beneficiary,beneficiary_known,hour,speed_kmh,in_trusted_zone,dist_from_home_km,ignition_on,is_tunnel,behavioral_score,label,driver_id
50,Mom,1,14,0,1,0.3,0,0,0.92,legit,drv_0001
150,Starbucks,1,9,20,1,4.2,1,0,0.88,legit,drv_0001
90000,unknown_merchant,0,2,95,0,52.7,1,1,0.14,suspicious,drv_0001
```

Older CSVs with just the first six columns still train fine (missing
optional columns fall back to inference-time defaults), but you leave real
signal on the table -- `behavior_anomaly` is the trained model's #1
feature by gain. Include the full schema whenever you can.

`driver_id` is optional but strongly recommended for larger sets: the
trainer computes **per-driver** `amount_z` when it's present, which
matches how inference computes amount_z from each driver's own rolling
mean/std via `ProfileStore.apply_to_context`. Without `driver_id`, the
trainer falls back to a global legit-only mean/std -- fine for a few
dozen rows but a train/serve distribution mismatch on any real dataset.

To generate a 50k-row synthetic set that satisfies the full schema and
passes the built-in QA gates, use `scripts/generate_risk_txns.py`:

```bash
python scripts/generate_risk_txns.py --seed 42 --n 50000 \
    --out data/driver1/transaction/txns.csv --meta meta.json
```

30+ rows is enough to start risk-model experiments later.

### Finger / behavioral / OOD (synthetic now → real HW later)

Until the fingerprint sensor / face cam / CAN recorder arrive, fill with:

```bash
python scripts/generate_phase3_synth.py
```

| Path | Contents |
|------|----------|
| `finger/enroll/` · `genuine/` · `attack/{wrong,partial,wet,dry,spoof}/` | Synthetic ridge PNGs |
| `behavioral/genuine/` · `attack/` | CAN/IMU CSV windows (8 features + `t_ms` + `label`): `steering_angle_deg`, `steering_rate_dps`, `throttle_pct`, `brake_pedal_pct`, `longitudinal_accel_g`, `lateral_accel_g`, `yaw_rate_dps`, `vehicle_speed_kmh` |
| `ood/face/` · `ood/voice/` · `ood/finger/` | Non-enrolled identity negatives |

**Manual scores (HW stand-in):** future sensors must emit `ModalityResult(score∈[0,1])`. For now:

```bash
# JSON file or inline
export DRIVEAUTH_MANUAL_SCORES=phases/manual_scores_happy.json
# or demo:
python scripts/phase3_synth_demo.py --scenario happy
python scripts/phase3_synth_demo.py --scores '{"finger":0.2,"behavioral":0.95}'
```

See `driveauth/matchers/score_provider.py`. When HW arrives, replace mock finger/behavioral classes — keep the same `capture_and_score` / `get_score` methods; DecisionEngine unchanged.

## Manifest (keep this updated)

`data/manifest.csv` columns:

```csv
path,driver_id,modality,split,notes,captured_at
driver1/voice/enroll/enroll_01.wav,driver1,voice,enroll,phrase pay mom,2026-07-10T17:00:00
```

After each capture session, append rows (or run the helper script if present).

## Session checklist (30–45 min)

1. Create folders under `data/driver1/...`
2. Record **5 enroll** voice + **5 enroll** face
3. Record **10 genuine** voice + **10 genuine** face
4. Record **5** of one attack class (replay voice *or* screen-face)
5. Write **30** transaction CSV rows
6. Update `manifest.csv`
7. Note consent: only your data / people who agreed



## Done when (Phase 3 → 2b gate)

- [x] `driver1` has enroll + genuine + ≥1 attack for **voice**
- [x] `driver1` has enroll + genuine + ≥1 attack for **face**
  (Robert Downey Jr via `scripts/populate_face_rdj.py` — replace with your face later)
- [x] `finger` / `behavioral` — synthetic via `scripts/generate_phase3_synth.py` (swap for HW later)
- [x] `ood/voice` + `ood/face` — Stage 1 real negatives (TTS + other-id stills);
      eval with `scripts/eval_ood_negatives.py` · finger OOD still synth
- [x] `transaction/txns.csv` — 50k synthetic rows shipped (Phase 3 txn modality done)
- [x] `manifest.csv` rows appended by populate / generate scripts

Then Phase **2b** can fine-tune; until then use Phase **2a** pretrained checkpoints only.

## Privacy

- Biometric data is sensitive — local disk, encrypted backup, no public git
- Prefer synthetic / self-data for early work
- Delete attack_replay sources that contain other people’s audio if not consented

