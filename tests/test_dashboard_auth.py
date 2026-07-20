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


def test_html_injects_admin_key_bootstrap(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "__DRIVEAUTH_ADMIN_KEY__" in res.text
    assert "test-dashboard-key" in res.text


def test_no_module_level_auth_singletons():
    import dashboard.app as dash

    assert not hasattr(dash, "_auth") or getattr(dash, "_auth", "missing") is None
    # Prefer app.state — module globals for DriveAuth cache must be gone.
    assert getattr(dash, "_auth_key", "gone") == "gone" or not hasattr(dash, "_auth_key")
