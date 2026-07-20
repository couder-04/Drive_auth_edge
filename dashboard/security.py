"""Lightweight dashboard admin authentication (MVP).

Protects purge / enroll / fraud / reset / profile and other mutating
admin endpoints with a shared secret from the environment.

Env
---
``DRIVEAUTH_DASHBOARD_API_KEY``
    Required Bearer / X-API-Key value for admin routes.

``DRIVEAUTH_ALLOW_INSECURE_DASHBOARD``
    When ``1`` and no API key is configured, admin routes are allowed
    (local demos only). Never enable on a network-exposed host.
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)

ENV_API_KEY = "DRIVEAUTH_DASHBOARD_API_KEY"
ENV_ALLOW_INSECURE = "DRIVEAUTH_ALLOW_INSECURE_DASHBOARD"


def configured_api_key() -> str | None:
    raw = (os.getenv(ENV_API_KEY) or "").strip()
    return raw or None


def allow_insecure_dashboard() -> bool:
    return (os.getenv(ENV_ALLOW_INSECURE) or "0").strip() == "1"


def admin_key_js_bootstrap() -> str:
    """Inline script so same-origin UI can attach the admin header.

    The dashboard binds to 127.0.0.1 by default; the key is already present
    on the server process. Empty string when insecure mode is used.
    """
    import json

    key = configured_api_key() or ""
    return (
        "<script>"
        f"window.__DRIVEAUTH_ADMIN_KEY__={json.dumps(key)};"
        f"window.__DRIVEAUTH_ADMIN_REQUIRED__={json.dumps(bool(key) or not allow_insecure_dashboard())};"
        "</script>"
    )


def require_admin(
    api_key: Annotated[str | None, Security(_API_KEY_HEADER)] = None,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)] = None,
) -> str:
    """FastAPI dependency — returns the authenticated principal label."""
    expected = configured_api_key()
    if expected is None:
        if allow_insecure_dashboard():
            return "insecure-local"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{ENV_API_KEY} is not set. Configure a secret or set "
                f"{ENV_ALLOW_INSECURE}=1 for local demos only."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided: str | None = None
    if api_key:
        provided = api_key.strip()
    elif bearer is not None and bearer.scheme.lower() == "bearer":
        provided = (bearer.credentials or "").strip()

    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing dashboard API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "admin"


AdminAuth = Annotated[str, Depends(require_admin)]
