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

Create `data/driver1/transaction/txns.csv`:

```csv
amount,beneficiary,beneficiary_known,hour,speed_kmh,in_trusted_zone,label
50,Mom,1,14,0,1,legit
150,Starbucks,1,9,20,1,legit
90000,unknown_merchant,0,2,95,0,suspicious
```

30+ rows is enough to start risk-model experiments later.

### Finger / behavioral / IR

Skip until you have a sensor or car log. Leave empty dirs.

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

- [ ] `driver1` has enroll + genuine + ≥1 attack for **voice**
- [ ] `driver1` has enroll + genuine + ≥1 attack for **face**
- [ ] `transaction/txns.csv` has ≥30 labeled rows
- [ ] `manifest.csv` lists every file

Then Phase **2b** can fine-tune; until then use Phase **2a** pretrained checkpoints only.

## Privacy

- Biometric data is sensitive — local disk, encrypted backup, no public git
- Prefer synthetic / self-data for early work
- Delete attack_replay sources that contain other people’s audio if not consented

