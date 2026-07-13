# Phase 2a — Pretrained models on Mac (no Thor, no fine-tune)

**Goal:** run the real matcher stack with off-the-shelf checkpoints. Finger/behavioral stay mock until hardware/models exist.

## Status checklist


| Step             | Command / artifact                                                      | Done? |
| ---------------- | ----------------------------------------------------------------------- | ----- |
| Install extras   | `pip install -e ".[voice,face,onnx,dev]"`                               | yes   |
| Download models  | `python scripts/phase2a_setup.py`                                       | ⬜     |
| Enroll templates | `python scripts/phase2a_enroll.py --synthetic` *(or real Phase 3 data)* | ⬜     |
| Demo auth        | `python scripts/phase2a_demo.py`                                        | ⬜     |
| Latency bench    | `python scripts/phase2a_demo.py --bench 20`                             | ⬜     |
| Record numbers   | append to `phases/phase2a-mac.txt`                                      | ⬜     |




## One-shot (Mac)

```bash
cd staged_driveauth-edge
source .venv/bin/activate   # if you use a venv
pip install -e ".[voice,face,onnx,dev]"

python scripts/phase2a_setup.py --store ./driveauth_store_phase2a
python scripts/phase2a_enroll.py --store ./driveauth_store_phase2a --synthetic
python scripts/phase2a_demo.py --store ./driveauth_store_phase2a
python scripts/phase2a_demo.py --store ./driveauth_store_phase2a --bench 20
```

`--synthetic` generates placeholder enroll WAVs/JPGs so you can verify the stack **before** finishing Phase 3 capture. Replace with real `data/driver1/*/enroll/` samples when ready (re-run enroll without `--synthetic`).

## What is “real” vs still mock


| Modality     | Phase 2a                          |
| ------------ | --------------------------------- |
| Voice        | SpeechBrain ECAPA-TDNN (VoxCeleb) |
| Face         | ArcFace-MobileFaceNet ONNX        |
| Finger       | mock (no sensor/model)            |
| Behavioral   | mock (no LSTM weights)            |
| Risk         | heuristic (unchanged)             |
| Trust fusion | static weights (unchanged)        |




## Hybrid load

`DriveAuth.load(..., use_mock_matchers=False)` uses each real matcher only when `ready`; otherwise falls back to mock for that modality so the pipeline never hard-crashes mid-Phase-2a.

## After this

- Keep collecting Phase 3 real enroll/genuine/attack data  
- Phase 2b = fine-tune on that data  
- Phase 1b = same commands on Thor for edge latency

