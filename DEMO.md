# DriveAuth Edge — Demo runbook (~6–8 min)

**Goal:** show Trust / Risk / Confidence → Policy, staged escalation, Mac + Thor, and Phase 3 data — without depending on real-face ACCEPT.

## One-line pitch

Edge biometric authorization for in-car payments: **who** you are (Trust) is scored separately from **how risky** the act is (Risk); a deterministic Policy decides ACCEPT / STEP_UP / REJECT.

## Pre-flight (5 min before)

```bash
cd /Users/par_04/code_playground/projects/staged_driveauth-edge
source .venv/bin/activate
bash scripts/demo_preflight.sh
```

Expect: pytest green · mock demo **ACCEPT**.

### Optional — Thor dashboard (second terminal on Mac)

```bash
# Terminal A — tunnel
ssh -p 10617 -L 8765:127.0.0.1:8765 acf-thor@fw1.sshreachme-trial.com

# Terminal B — on Thor (after SSH)
cd ~/staged_driveauth-edge && source .venv/bin/activate
unset DRIVEAUTH_DASHBOARD_PORT DRIVEAUTH_DASHBOARD_HOST
export DRIVEAUTH_USE_MOCK=1 DRIVEAUTH_DASHBOARD_HOST=0.0.0.0 DRIVEAUTH_DASHBOARD_PORT=8765
driveauth-dashboard
```

Mac browser: **http://127.0.0.1:8765**

---

## Talk flow

### 1. Problem (30 s)
In-vehicle payment / sensitive commands need strong auth without sending biometrics to the cloud every time.

### 2. Architecture (90 s) — open `README.md`
Show in order:
1. **Overview (simple)** — Inputs → Trust / Risk / Confidence → Policy → ACCEPT / STEP_UP / REJECT  
2. **Staged escalation (simple)** — Voice → Face → Finger, early-stop when strong enough  
3. Say: behaviour & GPS never enter Trust (only Risk)

### 3. Live mock ACCEPT (60 s) — Mac

```bash
DRIVEAUTH_USE_MOCK=1 driveauth-demo
```

Point at: **Decision ACCEPT** · Trust / Risk / Confidence · `early_stop` / probed voice · audit path.

Contrast (optional):

```bash
driveauth-demo --high-value
# expect STEP_UP / stricter path
```

### 4. Thor edge (60 s)
- `phases/mac.txt` vs `phases/thor.txt`  
- Mock p50: Mac **0.7 ms** · Thor **0.6 ms**  
- Open dashboard via tunnel if live; else show screenshot / say “verified on NVIDIA Thor”

### 5. Real models honesty (45 s)
- Phase 2a: **ECAPA-TDNN** + **MobileFaceNet** wired (`ready=True`)  
- Finger / behavioral still **mock**; risk still **heuristic**  
- Real-face ACCEPT deferred (`TODO.txt` — need same-person photos)

Do **not** run `phase2a_demo` unless you want to show STEP_UP as correct fail-safe.

### 6. Phase 3 dataset (45 s) — Finder / tree
```text
data/driver1/voice/   enroll · genuine · attacks
data/driver1/face/    enroll · genuine · attacks
data/driver1/transaction/txns.csv   30 labeled rows
```
Unlocks Phase 2b fine-tune / risk training next.

### 7. Close (20 s)
Shipped: full policy stack · Mac+Thor mock · pretrained voice/face path · labeled data.  
Next: better faces · train `risk_gbt.onnx` · calibrate thresholds.

---

## Numbers to memorize

| Item | Value |
|------|--------|
| Mock auth p50 | Mac 0.7 ms · Thor 0.6 ms |
| Real ECAPA p50 (Mac) | ~31 ms |
| Tests | 50 passed (Mac & Thor) |
| Voice / face / txns | 8+20+7 · 5+20+15 · 30 rows |

## Do / don’t

| Do | Don’t |
|----|--------|
| Show mock ACCEPT as “pipeline works” | Claim production anti-spoof / PAD |
| Show STEP_UP on `--high-value` as policy | Claim finger/behavioral are real |
| Cite Thor `phases/thor.txt` | Depend on mixed-ID face ACCEPT |

## Backup if something fails

1. `DRIVEAUTH_USE_MOCK=1 driveauth-demo` only  
2. README diagrams only  
3. `phases/mac.txt` + `phases/thor.txt` side by side  
4. `data/` folder walk
