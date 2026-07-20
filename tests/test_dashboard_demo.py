"""Dashboard demo polish — read-only API shape tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVEAUTH_USE_MOCK", "1")
    monkeypatch.setenv("DRIVEAUTH_DASHBOARD_STORE", str(tmp_path / "store"))
    monkeypatch.delenv("DRIVEAUTH_DEMO_MODE", raising=False)
    # Fresh module-level auth cache between tests.
    import dashboard.app as dash

    dash._auth = None
    dash._auth_key = None
    return TestClient(app)


def test_authenticate_payload_includes_stage3_and_driver(client):
    res = client.post(
        "/api/authenticate",
        json={
            "amount": 50.0,
            "beneficiary": "Mom",
            "beneficiary_known": True,
            "mock_scores": {"voice": 0.95, "face": 0.9, "finger": 0.9, "behavioral": 0.95},
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] in ("ACCEPT", "REJECT", "STEP_UP_REQUIRED")
    assert "stage3_method" in data
    assert "decision_driver" in data
    assert "lane" in data["decision_driver"]
    assert "summary" in data["decision_driver"]
    assert "policy_tags" in data
    assert isinstance(data["policy_tags"], list)
    pipe = data["pipeline"]
    assert "stage3_method" in pipe
    ladder = next(s for s in pipe["stages"] if s["id"] == "ladder")
    assert "stage3_lanes" in ladder
    lane_ids = {x["id"] for x in ladder["stage3_lanes"]}
    assert lane_ids == {"finger", "otp"}
    decision_stage = next(s for s in pipe["stages"] if s["id"] == "decision")
    assert decision_stage["status"] in ("accept", "reject", "stepup", "hold", "done", "block")


def test_otp_fallback_scenario_sets_stage3_method(client):
    res = client.post(
        "/api/authenticate",
        json={
            "amount": 150.0,
            "beneficiary_known": True,
            "mock_scores": {"voice": 0.4, "face": 0.4, "finger": None, "behavioral": 0.95},
            "fingerprint_available": False,
            "stage3_mode": "finger_or_otp",
            "otp_demo": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "ACCEPT"
    assert data["stage3_method"] == "otp_bluetooth"
    assert data["pipeline"]["accept_modality"] == "otp"
    assert data["pipeline"]["stage3_fallback"] is True
    lanes = next(s for s in data["pipeline"]["stages"] if s["id"] == "ladder")[
        "stage3_lanes"
    ]
    by_id = {x["id"]: x for x in lanes}
    assert by_id["finger"]["status"] == "unavailable"
    assert by_id["otp"]["status"] == "accept"


def test_audit_verify_shape(client):
    client.post(
        "/api/authenticate",
        json={"amount": 50.0, "beneficiary_known": True},
    )
    res = client.get("/api/audit/verify")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["reason"] == "ok"
    assert body["demo_mode"] is False


def test_demo_tamper_gated(client, monkeypatch):
    client.post(
        "/api/authenticate",
        json={"amount": 50.0, "beneficiary_known": True},
    )
    blocked = client.post("/api/audit/demo_tamper")
    assert blocked.status_code == 403

    monkeypatch.setenv("DRIVEAUTH_DEMO_MODE", "1")
    import dashboard.app as dash

    dash._auth = None
    dash._auth_key = None
    ok = client.post("/api/audit/demo_tamper")
    assert ok.status_code == 200
    body = ok.json()
    assert body["tampered"] is True
    assert body["verify"]["ok"] is False


def test_modality_sources_shape(client):
    res = client.get("/api/modality_sources")
    assert res.status_code == 200
    body = res.json()
    assert "modalities" in body
    for key in ("voice", "face", "finger", "liveness", "can"):
        assert key in body["modalities"]
        assert "label" in body["modalities"][key]
    assert "hailo_status" in body
    assert "Hailo" in body["hailo_status"] or "hailo" in body["hailo_status"].lower()
    assert "face_backend" in body


def test_scenarios_include_featured(client):
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    ids = {s["id"] for s in res.json()}
    assert "genuine_driver" in ids
    assert "finger_otp_fallback" in ids
    assert "face_replay" in ids
    assert "zone_novel_stepup" in ids
    otp = next(s for s in res.json() if s["id"] == "finger_otp_fallback")
    assert otp["request"]["otp_demo"] is True
    assert otp["request"]["stage3_mode"] == "finger_or_otp"
    assert otp["request"]["fingerprint_available"] is False
