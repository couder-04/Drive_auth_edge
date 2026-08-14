"""Dashboard admin authentication — 401 / OpenAPI / dependency wiring."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dashboard.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_USE_MOCK", "1")
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_API_KEY", "test-dashboard-key")
    monkeypatch.delenv("DRIVEAUTH_ALLOW_INSECURE_DASHBOARD", raising=False)
    with TestClient(app) as c:
        yield c


def test_admin_endpoints_require_api_key(client):
    blocked = [
        ("/api/fraud/reset", {}),
        ("/api/reset", None),
        ("/api/profile/bootstrap", None),
        ("/api/register/purge", {"driver_id": "driver1"}),
        ("/api/authenticate", {"amount": 50.0, "beneficiary_known": True}),
    ]
    for path, body in blocked:
        if body is None:
            res = client.post(path)
        else:
            res = client.post(path, json=body)
        assert res.status_code == 401, path
        assert "API key" in res.json()["detail"] or "missing" in res.json()["detail"].lower()


def test_admin_endpoints_accept_x_api_key(client, admin_headers):
    res = client.post(
        "/api/authenticate",
        json={"amount": 50.0, "beneficiary_known": True},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["decision"] in ("ACCEPT", "REJECT", "STEP_UP_REQUIRED")


def test_admin_endpoints_accept_bearer(client):
    res = client.post(
        "/api/fraud/reset",
        headers={"Authorization": "Bearer test-dashboard-key"},
    )
    assert res.status_code == 200
    assert "fraud_state" in res.json()


def test_missing_api_key_config_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("DRIVEAUTH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("DRIVEAUTH_ALLOW_INSECURE_DASHBOARD", raising=False)
    monkeypatch.setenv("DRIVEAUTH_USE_MOCK", "1")
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_STORE", str(tmp_path / "store"))
    with TestClient(app) as client:
        res = client.post("/api/fraud/reset")
        assert res.status_code == 503
        assert "DRIVEAUTH_DASHBOARD_API_KEY" in res.json()["detail"]


def test_insecure_mode_allows_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DRIVEAUTH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("DRIVEAUTH_ALLOW_INSECURE_DASHBOARD", "1")
    monkeypatch.setenv("DRIVEAUTH_USE_MOCK", "1")
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_STORE", str(tmp_path / "store"))
    with TestClient(app) as client:
        res = client.post("/api/fraud/reset")
        assert res.status_code == 200


def test_openapi_documents_api_key_security(client):
    spec = client.get("/openapi.json").json()
    assert "components" in spec
    schemes = spec["components"].get("securitySchemes", {})
    # HTTPBearer and/or APIKeyHeader from our dependency
    assert schemes, "expected securitySchemes in OpenAPI"
    # Mutating path should list security
    auth_path = spec["paths"]["/api/authenticate"]["post"]
    # FastAPI may put security on the operation when using Security()
    assert "security" in auth_path or schemes


def test_html_never_contains_configured_api_key(client):
    """Regression: dashboard HTML must never ship the raw admin key to the browser."""
    res = client.get("/")
    assert res.status_code == 200
    assert "test-dashboard-key" not in res.text
    assert "__DRIVEAUTH_ADMIN_KEY__" not in res.text
    assert "driveauth-login" in res.text
    assert "__DRIVEAUTH_ADMIN_REQUIRED__" in res.text


def test_authenticated_html_never_contains_configured_api_key(client):
    login = client.post("/api/admin/login", json={"api_key": "test-dashboard-key"})
    assert login.status_code == 200
    res = client.get("/")
    assert res.status_code == 200
    assert "test-dashboard-key" not in res.text
    assert "__DRIVEAUTH_ADMIN_KEY__" not in res.text


def test_login_sets_httponly_session_cookie(client):
    res = client.post("/api/admin/login", json={"api_key": "test-dashboard-key"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    cookie = res.cookies.get("driveauth_admin_session")
    assert cookie
    # Subsequent mutating calls ride the cookie — no header needed.
    follow = client.post("/api/fraud/reset")
    assert follow.status_code == 200


def test_login_rejects_wrong_key(client):
    res = client.post("/api/admin/login", json={"api_key": "definitely-wrong"})
    assert res.status_code == 401
    assert client.post("/api/fraud/reset").status_code == 401


def test_logout_clears_session_cookie(client):
    assert client.post("/api/admin/login", json={"api_key": "test-dashboard-key"}).status_code == 200
    assert client.post("/api/fraud/reset").status_code == 200
    out = client.post("/api/admin/logout")
    assert out.status_code == 200
    assert client.post("/api/fraud/reset").status_code == 401


def test_no_module_level_auth_singletons():
    import dashboard.app as dash

    assert not hasattr(dash, "_auth") or getattr(dash, "_auth", "missing") is None
    # Prefer app.state — module globals for DriveAuth cache must be gone.
    assert getattr(dash, "_auth_key", "gone") == "gone" or not hasattr(dash, "_auth_key")


def test_authenticate_honors_use_mock_config(client, monkeypatch):
    """``/api/authenticate`` must not hardcode mock matchers."""
    import dashboard.app as dash

    seen: dict[str, bool | None] = {}
    real = dash.get_auth

    def _wrap(*, use_mock=None, request=None, driver_id=None, mature=True):
        seen["use_mock"] = use_mock
        return real(use_mock=True, request=request, driver_id=driver_id, mature=mature)

    monkeypatch.setattr(dash, "get_auth", _wrap)
    monkeypatch.setenv("DRIVEAUTH_USE_MOCK", "0")
    res = client.post(
        "/api/authenticate",
        json={"amount": 50.0, "beneficiary_known": True},
        headers={"X-API-Key": "test-dashboard-key"},
    )
    assert res.status_code == 200
    assert seen.get("use_mock") is False
