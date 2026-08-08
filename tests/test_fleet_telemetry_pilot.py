"""Fleet telemetry pilot — opt-in reporter + ingest endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import app
from hardware.fleet_telemetry import (
    FleetTelemetryIngest,
    FleetTelemetryReporter,
    build_telemetry_payload,
    fleet_opt_in_enabled,
)

ADMIN_HEADERS = {"X-API-Key": "test-dashboard-key"}


def _client():
    c = TestClient(app)
    c.headers.update(ADMIN_HEADERS)
    return c


def test_fleet_opt_in_requires_explicit_flag(monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_FLEET_TELEMETRY_URL", "http://example/ingest")
    monkeypatch.delenv("DRIVEAUTH_FLEET_TELEMETRY_OPT_IN", raising=False)
    rep = FleetTelemetryReporter(url="http://example/ingest")
    assert rep.enabled is False

    monkeypatch.setenv("DRIVEAUTH_FLEET_TELEMETRY_OPT_IN", "1")
    rep2 = FleetTelemetryReporter(url="http://example/ingest")
    assert rep2.enabled is True


def test_fleet_telemetry_ingest_endpoint(tmp_path: Path, monkeypatch):
    import dashboard.app as app_mod

    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    client = _client()
    body = {
        "schema": "driveauth.fleet_telemetry.v1",
        "vehicle_id": "veh1",
        "firmware_version": "0.2.0",
        "auth": {"accept": 3, "reject": 1, "step_up": 0},
        "sensors": {"voice": True, "face": True, "finger": False},
    }
    r = client.post("/api/fleet/telemetry", json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    rows = FleetTelemetryIngest(store / "fleet_telemetry" / "ingest.jsonl").recent()
    assert len(rows) == 1
    assert rows[0]["vehicle_id"] == "veh1"
    assert rows[0]["auth"]["accept"] == 3

    r2 = client.get("/api/fleet/telemetry")
    assert r2.status_code == 200
    assert r2.json()["count"] == 1


def test_fleet_health_includes_telemetry_status(tmp_path: Path, monkeypatch):
    import dashboard.app as app_mod

    store = tmp_path / "store"
    (store / "audit").mkdir(parents=True)
    (store / "audit" / "driveauth_events.jsonl").write_text(
        json.dumps({"decision": "ACCEPT"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    client = _client()
    r = client.get("/api/fleet/health")
    assert r.status_code == 200
    assert "telemetry" in r.json()
    assert "opt_in" in r.json()["telemetry"]


def test_fleet_reporter_builds_payload(tmp_path: Path):
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n".join(
            [
                json.dumps({"decision": "ACCEPT"}),
                json.dumps({"decision": "REJECT"}),
                json.dumps({"decision": "STEP_UP_REQUIRED"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rep = FleetTelemetryReporter(audit_path=audit, url="")
    payload = rep.build_payload()
    assert payload["auth"]["accept"] == 1
    assert payload["auth"]["reject"] == 1
    assert payload["auth"]["step_up"] == 1
