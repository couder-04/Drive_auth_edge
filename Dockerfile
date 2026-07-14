# DriveAuth Edge — standalone dashboard (Railway / Docker)
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DRIVEAUTH_DASHBOARD_HOST=0.0.0.0 \
    DRIVEAUTH_USE_MOCK=0 \
    DRIVEAUTH_DASHBOARD_STORE=/data/store \
    DRIVEAUTH_REGISTER_STORE=/data/store \
    DRIVEAUTH_DATA_ROOT=/data/data \
    HF_HOME=/data/hf \
    TORCH_HOME=/data/torch \
    SPEECHBRAIN_CACHE=/data/hf

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libsndfile1 \
      ffmpeg \
      libgl1 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY driveauth ./driveauth
COPY dashboard ./dashboard
COPY demo ./demo
COPY scripts ./scripts
COPY driveauth_store_pha ./driveauth_store_pha

RUN pip install --upgrade pip \
 && pip install -e ".[voice,face,onnx,dashboard]"

RUN mkdir -p /data/store /data/data /data/hf /data/torch \
 && cp -a /app/driveauth_store_pha/. /data/store/

EXPOSE 8765
# Railway sets $PORT. Seed models via volume or scripts/phase2a_setup.py on first boot.
CMD ["sh", "-c", "driveauth-dashboard --host 0.0.0.0 --port ${PORT:-8765} --strict-port"]
