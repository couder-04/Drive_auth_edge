# Railway deploy runbook (persistent `/data` volume)

This guide closes **TODO (4)** from an ops perspective. The repo ships
Dockerfile + `railway.toml`; you attach the volume and env in Railway UI.

## 1. Create service

1. Connect GitHub repo → **Deploy from Dockerfile** (`railway.toml` sets this).
2. Set **internal port** `8765` (healthcheck: `/api/standalone/config`).

## 2. Attach persistent volume

| Mount path | Purpose |
|------------|---------|
| `/data/store` | Encrypted templates, ONNX heads, audit log, fleet ingest |
| `/data/data` | Enroll captures (`data/<driver_id>/…`) |
| `/data/hf` | HuggingFace / SpeechBrain cache |
| `/data/torch` | Torch hub cache |

Railway: **Settings → Volumes → Add volume → mount at `/data`**.

The container entry runs `scripts/railway_first_boot.sh` before the dashboard;
it seeds an empty volume from bundled `driveauth_store_pha` when no face model
is present.

## 3. Required environment variables

Copy from `secrets.env.example`. Minimum for a public standalone demo:

```bash
DRIVEAUTH_DASHBOARD_API_KEY=<generate with secrets.token_urlsafe>
OPENROUTER_API_KEY=<your key>
GOOGLE_MAPS_API_KEY=<optional, for /register home map>
DRIVEAUTH_USE_MOCK=0
DRIVEAUTH_DASHBOARD_STORE=/data/store
DRIVEAUTH_REGISTER_STORE=/data/store
DRIVEAUTH_DATA_ROOT=/data/data
DRIVEAUTH_DEFAULT_DRIVER=driver1
```

Optional fleet telemetry (pilot):

```bash
DRIVEAUTH_FLEET_TELEMETRY_OPT_IN=1
DRIVEAUTH_FLEET_TELEMETRY_URL=https://<your-service>.up.railway.app/api/fleet/telemetry
DRIVEAUTH_VEHICLE_ID=vehicle_01
```

## 4. Post-deploy seed (if models missing)

Shell into the running container or run a one-off job:

```bash
python scripts/phase2a_setup.py --store /data/store
python scripts/phase2a_enroll.py --store /data/store --data /data/data/driver1
```

Register additional drivers via `https://<service>.up.railway.app/register`.

## 5. RAM guidance

- **≥4 GB** recommended with live ECAPA + MobileFaceNet (CPU ONNX).
- Set `DRIVEAUTH_USE_MOCK=1` only for UI demos without real matchers.

## 6. Replace Cloudflare tunnel demo

Once `/data` volume + env are set, the Railway URL is the durable public endpoint.
Retire the Mac + `cloudflared` tunnel used for local demos.
