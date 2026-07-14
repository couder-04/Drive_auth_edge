"""Load product secrets from ``secrets.env`` without overriding real env."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("driveauth.secrets")

_LOADED = False


def _default_secrets_path() -> Path:
    override = os.getenv("DRIVEAUTH_SECRETS_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # Repo root (parent of driveauth/)
    return Path(__file__).resolve().parents[1] / "secrets.env"


def load_secrets(*, path: Path | None = None, override: bool = False) -> Path | None:
    """Parse KEY=VALUE lines into ``os.environ``.

    Existing environment variables win unless ``override=True``.
    Returns the path loaded, or ``None`` if the file is missing.
    """
    global _LOADED
    secrets_path = path or _default_secrets_path()
    if not secrets_path.is_file():
        logger.debug("secrets file not found: %s", secrets_path)
        _LOADED = True
        return None

    count = 0
    for raw in secrets_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if not key:
            continue
        if not override and key in os.environ and os.environ[key] != "":
            continue
        os.environ[key] = val
        count += 1
    logger.info("Loaded %d secret(s) from %s", count, secrets_path)
    _LOADED = True
    return secrets_path


def ensure_secrets_loaded() -> None:
    if not _LOADED:
        load_secrets()


def get_secret(name: str, default: str = "") -> str:
    ensure_secrets_loaded()
    return os.getenv(name, default) or default


def openrouter_configured() -> bool:
    return bool(get_secret("OPENROUTER_API_KEY").strip())


def google_maps_key() -> str:
    return get_secret("GOOGLE_MAPS_API_KEY").strip()
