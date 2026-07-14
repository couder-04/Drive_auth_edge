# Standalone DriveAuth (OpenRouter + Railway)

Run DriveAuth as a product without Nova: cloud STT/TTS, robust intent
slot-fill, live ECAPA + face, Maps home/GPS, finger still manual.

Dashboard pages (same server):

| Page | Path | Role |
|------|------|------|
| Manual pipeline | `/manual` (also `/`) | Slider scores + presets |
| Standalone pay | `/standalone` | Mic → STT → slots → TTS → live auth |
| Register | `/register` | Drivers list · face/voice capture · home pin · enroll |

Both Manual and Standalone share **Actions**, **Live security pipeline**,
**Result**, and **Audit log**.

## 1. Secrets

```bash
cp secrets.env.example secrets.env
# edit secrets.env — paste keys
```

| Key | Purpose |
|-----|---------|
| `OPENROUTER_API_KEY` | STT + TTS + LLM clarification |
| `OPENROUTER_STT_MODEL` | default `openai/whisper-1` |
| `OPENROUTER_TTS_MODEL` | default `openai/gpt-4o-mini-tts` |
| `OPENROUTER_LLM_MODEL` | default `openai/gpt-4o-mini` |
| `GOOGLE_MAPS_API_KEY` | JS Maps home + pay location pickers |
| `DRIVEAUTH_USE_MOCK` | `0` = live biometrics |
| `DRIVEAUTH_*_STORE` | keep register + auth on the **same** path |

`secrets.env` is gitignored. On Railway, paste the same keys into **Variables**.

Intent LLM system prompt: `INTENT_SYSTEM_PROMPT` in
[`driveauth/openrouter_client.py`](../driveauth/openrouter_client.py) — fills
**Amount / Beneficiary / Action / Currency**, and on ambiguity returns
`ask_field` + TTS text that names the column.

Restrict the Google Maps key by HTTP referrer to your public host + `localhost`.

## 2. Local run

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[standalone]"
python scripts/phase2a_setup.py --store ./driveauth_store_phase2a
python scripts/phase2a_enroll.py --store ./driveauth_store_phase2a --data ./data/driver1
driveauth-dashboard --host 127.0.0.1 --port 8765
```

1. Open `/register` → check **Registered drivers** → capture / enroll → pin home  
2. Open `/standalone` → talk → slot fill (TTS if a column is missing) → pin GPS → authorize  
3. Staircase (Voice → Face → Finger) + Result + Audit update live  
4. `/manual` still works for slider demos without cloud keys  

Quick tunnel (Mac must stay awake):

```bash
cloudflared tunnel --url http://127.0.0.1:8765
```

## 3. API sketch

| Endpoint | Role |
|----------|------|
| `GET /api/standalone/config` | Maps key + drivers + OpenRouter flag |
| `POST /api/standalone/transcribe` | WAV → STT → intent (± TTS, `ask_field`) |
| `POST /api/standalone/intent` | text → intent (± TTS) |
| `POST /api/standalone/auth` | multipart live voice/face + GPS |
| `GET /api/register/drivers` | registered drivers + enrollment status |
| `POST /api/register/home` | explicit home pin |

## 4. Railway (always-on, Mac can sleep)

1. Push this repo to GitHub.  
2. New Railway project → Deploy from GitHub → Dockerfile.  
3. Attach a **volume** at `/data` (store + enroll data + HF cache).  
4. Set variables from `secrets.env.example`.  
5. Prefer **≥4 GB RAM** (SpeechBrain/torch).  
6. After first deploy, seed store/enrollments (one-off shell):

```bash
python scripts/phase2a_setup.py --store /data/store
python scripts/phase2a_enroll.py --store /data/store --data /data/data/driver1
```

Public URL: `https://<service>.up.railway.app`

Health check: `GET /api/standalone/config`.

## 5. Flow

```text
mic → OpenRouter STT → regex + LLM columns
     → (ambiguous/missing) TTS names ask_field column → mic
     → Maps GPS → dist_from_home via ProfileStore.set_home / location_context
     → ECAPA voice (± face JPEG) · finger slider
     → Policy + staircase UI
```

Nova integration stays available via `DriveAuth.intercept()` — this product path is optional.
