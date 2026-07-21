# Driver1 re-collect + retrain — STOPPED at Step 2 (hardware)

**Date:** 2026-07-21  
**Status:** Step 1 confirmed; Step 2 blocked in this agent environment (no Camera/Mic TCC).  
**Do not retrain yet** — old far-field genuines are still on disk.

---

## Step 1 — Prerequisite fixes (CONFIRMED)

| Check | Result |
|-------|--------|
| Fallback meta on Haar miss | `face_frac=None`, `frontal_ok=False`, `inject_fallback=True` — **not** `1.0`/`True` |
| `_run_pad` unknown meta | fail-closed (`pad_ok=False`, modality unscored) |
| PAD feature default for `face_frac=None` | **0.0** (not 1.0) |
| Capture convention | `CAPTURE_FRAME_WIDTH/HEIGHT = 640×480` + `assess_face_framing` gate |
| Soft Haar | **not adopted** (stock 1.1 / 5 kept) |
| Genuine capture hint | close-up only (no “vary distance”) |

## attack_side decision

Leave attacks untouched. Current `attack_side`: **4/8 Haar-OK**, 4 fallback.  
Train PAD with `--exclude-fallback-crops` so Haar-miss sides never enter the fit.  
Fabricated-meta fix does **not** require re-capturing sides — it changes how misses are *labeled*, not what a valid side attack looks like.

## Step 2 — Why the agent stopped

- OpenCV / ffmpeg AVFoundation: **no camera or mic devices** visible to the Cursor agent process (macOS TCC).
- Cannot launch Terminal.app from this sandbox (`Unable to find application named 'Terminal'`).

Existing data still on disk (unchanged):

| Split | n |
|-------|--:|
| face/genuine (old 1080p) | 20 |
| voice/genuine | 20 |
| face/enroll | 8 |
| voice/enroll | 8 |

---

## What you run locally (Terminal.app / iTerm — grant Camera + Microphone)

```bash
cd /Users/par_04/Desktop/staged_driveauth-edge
source .venv/bin/activate
set -a && source secrets.env && set +a

# Face 22 + voice 24 (backs up old genuine_* into *_backup_<timestamp>/)
python scripts/recapture_driver1_genuine.py --face-n 22 --voice-n 24 --camera 0

# Or face-only / voice-only:
# python scripts/recapture_driver1_genuine.py --face-n 22 --skip-voice
# python scripts/recapture_driver1_genuine.py --voice-n 24 --skip-face
```

Face: fill the green oval, hold still — auto-saves only on Haar OK.  
Voice: Enter before each prompted phrase (~3.5 s, 16 kHz).

**Target:** face Haar hit-rate ≫ old **3/20 (15%)** / overall **58.8%** — expect ~≥95% on new close-ups.

Then reply here (or run):

```bash
python scripts/driver1_post_recapture_pipeline.py
```

That script verifies hit-rate → trains `faces/driver1/` + `voices/driver1/` only → live PAD diagnostic → stock-bar `audit_driver1_e2e.py` → `overfit_audit_stage2.py`.  
It does **not** source `phase2b_suggested.env`.

---

## Helper scripts added (uncommitted)

- `scripts/recapture_driver1_genuine.py`
- `scripts/driver1_post_recapture_pipeline.py`
- `scripts/_launch_driver1_recapture.sh`
