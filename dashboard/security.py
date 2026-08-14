"""Dashboard admin authentication.

Protects purge / enroll / fraud / reset / profile and other mutating
admin endpoints with a shared secret from the environment.

Browser UI uses an HttpOnly session cookie set by ``POST /api/admin/login``.
Programmatic clients may still send Bearer / ``X-API-Key``. The raw API key
is never serialized into HTML or JavaScript.

Env
---
``DRIVEAUTH_DASHBOARD_API_KEY``
    Required Bearer / X-API-Key value for admin routes (and login body).

``DRIVEAUTH_ALLOW_INSECURE_DASHBOARD``
    When ``1`` and no API key is configured, admin routes are allowed
    (local demos only). Never enable on a network-exposed host.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)

ENV_API_KEY = "DRIVEAUTH_DASHBOARD_API_KEY"
ENV_ALLOW_INSECURE = "DRIVEAUTH_ALLOW_INSECURE_DASHBOARD"

SESSION_COOKIE = "driveauth_admin_session"
SESSION_TTL_S = 8 * 3600.0

# Used only if lifespan has not attached DashboardState yet.
_orphan_sessions: dict[str, float] = {}


def configured_api_key() -> str | None:
    raw = (os.getenv(ENV_API_KEY) or "").strip()
    return raw or None


def allow_insecure_dashboard() -> bool:
    return (os.getenv(ENV_ALLOW_INSECURE) or "0").strip() == "1"


def admin_required() -> bool:
    """True when a key is configured, or insecure mode is off (503 until configured)."""
    if configured_api_key():
        return True
    return not allow_insecure_dashboard()


def _key_matches(provided: str, expected: str) -> bool:
    if len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def verify_configured_key(provided: str) -> bool:
    expected = configured_api_key()
    if expected is None:
        return False
    return _key_matches((provided or "").strip(), expected)


def issue_session(request: Request) -> str:
    dash = getattr(request.app.state, "dashboard", None)
    token = secrets.token_urlsafe(32)
    expiry = time.monotonic() + SESSION_TTL_S
    if dash is not None:
        dash.put_session(token, expiry)
    else:
        _orphan_sessions[token] = expiry
    return token


def session_valid(request: Request, token: str | None) -> bool:
    if not token:
        return False
    now = time.monotonic()
    dash = getattr(request.app.state, "dashboard", None)
    if dash is not None:
        return dash.session_valid(token, now)
    expiry = _orphan_sessions.get(token)
    if expiry is None or expiry < now:
        _orphan_sessions.pop(token, None)
        return False
    return True


def revoke_session(request: Request, token: str | None) -> None:
    if not token:
        return
    dash = getattr(request.app.state, "dashboard", None)
    if dash is not None:
        dash.revoke_session(token)
    else:
        _orphan_sessions.pop(token, None)


def request_has_admin_session(request: Request) -> bool:
    return session_valid(request, request.cookies.get(SESSION_COOKIE))


def set_session_cookie(request: Request, response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        max_age=int(SESSION_TTL_S),
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def session_ui_html(*, required: bool, authenticated: bool) -> str:
    """Login overlay + session flag. Never includes the API key."""
    import json

    required_js = json.dumps(bool(required))
    authed_js = json.dumps(bool(authenticated))
    overlay_display = "flex" if required and not authenticated else "none"
    return f"""<style>
#driveauth-login {{
  display: {overlay_display};
  position: fixed; inset: 0; z-index: 9999;
  align-items: center; justify-content: center;
  background: rgba(6, 10, 16, 0.72);
  font-family: system-ui, sans-serif;
}}
#driveauth-login form {{
  background: #0e1624; color: #e7eef8; border: 1px solid #243247;
  border-radius: 12px; padding: 1.25rem 1.4rem; width: min(360px, 92vw);
}}
#driveauth-login h2 {{ margin: 0 0 0.4rem; font-size: 1.05rem; }}
#driveauth-login p {{ margin: 0 0 0.85rem; color: #8fa3bc; font-size: 0.85rem; }}
#driveauth-login input {{
  width: 100%; box-sizing: border-box; margin: 0 0 0.7rem;
  padding: 0.5rem 0.6rem; border-radius: 8px; border: 1px solid #35506e;
  background: #060a10; color: #e7eef8;
}}
#driveauth-login button {{
  width: 100%; padding: 0.5rem; border: 0; border-radius: 8px;
  background: #38bdf8; color: #061018; font-weight: 600; cursor: pointer;
}}
#driveauth-login .err {{ color: #f87171; font-size: 0.8rem; min-height: 1.1em; margin: 0 0 0.4rem; }}
</style>
<div id="driveauth-login" role="dialog" aria-modal="true" aria-labelledby="driveauth-login-title">
  <form id="driveauth-login-form" autocomplete="off">
    <h2 id="driveauth-login-title">Dashboard login</h2>
    <p>Enter the server admin key. It is never stored in the page.</p>
    <p class="err" id="driveauth-login-err"></p>
    <input id="driveauth-login-key" type="password" name="api_key" placeholder="Admin API key" required />
    <button type="submit">Sign in</button>
  </form>
</div>
<script>
window.__DRIVEAUTH_ADMIN_REQUIRED__={required_js};
window.__DRIVEAUTH_ADMIN_SESSION__={authed_js};
(function () {{
  const form = document.getElementById("driveauth-login-form");
  if (!form) return;
  form.addEventListener("submit", async function (ev) {{
    ev.preventDefault();
    const err = document.getElementById("driveauth-login-err");
    err.textContent = "";
    const key = (document.getElementById("driveauth-login-key").value || "").trim();
    try {{
      const res = await fetch("/api/admin/login", {{
        method: "POST",
        credentials: "same-origin",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ api_key: key }}),
      }});
      if (!res.ok) {{
        const data = await res.json().catch(function () {{ return {{}}; }});
        err.textContent = data.detail || "Login failed";
        return;
      }}
      window.location.reload();
    }} catch (e) {{
      err.textContent = (e && e.message) || "Login failed";
    }}
  }});
}})();
</script>
"""


def require_admin(
    request: Request,
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

    if provided is not None:
        if _key_matches(provided, expected):
            return "admin"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing dashboard API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if session_valid(request, request.cookies.get(SESSION_COOKIE)):
        return "admin-session"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing dashboard API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


AdminAuth = Annotated[str, Depends(require_admin)]
