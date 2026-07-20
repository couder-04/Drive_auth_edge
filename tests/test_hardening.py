"""Production-hardening Phases B–I unit tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from driveauth.audit_log import AuditLog, GENESIS_HASH, score_bucket, verify_chain
from driveauth.consent import ConsentRequiredError, record_consent, require_consent
from driveauth.integrity import (
    IntegrityError,
    dump_public_key,
    generate_keypair,
    sign_manifest,
    verify_store_integrity,
)
from driveauth.purge import biometric_residue, purge_driver
from driveauth.template_store import ensure_key, save_embedding
from driveauth.types import Decision, DriveAuthResult
from hardware.actuation import (
    ActuationListener,
    ActuationWatchdog,
    FlakyAckRelay,
    NullRelay,
    NullSpeaker,
)
from hardware.fleet_telemetry import (
    FORBIDDEN_KEYS,
    assert_no_biometric_content,
    build_telemetry_payload,
)
from hardware.ota_client import OTAClient, OTAError, verify_update_package


def _result(**kwargs) -> DriveAuthResult:
    base = dict(
        trust_score=0.9,
        risk_score=0.1,
        confidence_score=0.85,
        decision=Decision.ACCEPT,
        driver_id="driver1",
        session_id="sess",
    )
    base.update(kwargs)
    return DriveAuthResult(**base)


# ── Phase B ──────────────────────────────────────────────────────────────────


def test_audit_hash_chain_verifies(tmp_path: Path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.log_decision(event="auth", driver_id="d1", result=_result())
    log.log_decision(
        event="auth",
        driver_id="d1",
        result=_result(decision=Decision.REJECT, trust_score=0.1),
    )
    ok, reason = log.verify_chain()
    assert ok, reason
    entries = log.read_all_entries()
    assert entries[0]["prev_hash"] == GENESIS_HASH
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
    assert "trust_bucket" in entries[0]


def test_audit_chain_detects_tamper(tmp_path: Path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.log_decision(event="auth", driver_id="d1", result=_result())
    log.log_decision(event="auth", driver_id="d1", result=_result(trust_score=0.5))
    lines = path.read_text(encoding="utf-8").splitlines()
    mid = json.loads(lines[0])
    mid["trust_score"] = 0.0  # tamper without updating hash
    lines[0] = json.dumps(mid)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, reason = verify_chain([json.loads(x) for x in lines])
    assert ok is False
    assert "mismatch" in reason


def test_audit_chain_detects_removed_entry(tmp_path: Path):
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.log_decision(event="auth", driver_id="d1", result=_result(trust_score=0.5 + i * 0.1))
    lines = path.read_text(encoding="utf-8").splitlines()
    # Drop middle entry — prev_hash of last no longer matches.
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, reason = AuditLog(path).verify_chain()
    assert ok is False


def test_audit_remote_sink_mocked(tmp_path: Path):
    shipped: list[bytes] = []

    def sink(url, body, headers):
        assert url == "https://audit.example/ingest"
        assert headers["Content-Type"] == "application/json"
        shipped.append(body)

    log = AuditLog(
        tmp_path / "a.jsonl",
        remote_url="https://audit.example/ingest",
        remote_sink=sink,
    )
    log.log_decision(event="auth", driver_id="d1", result=_result())
    assert len(shipped) == 1
    entry = json.loads(shipped[0])
    assert entry["entry_hash"]
    assert entry["decision"] == "ACCEPT"


# ── Phase C ──────────────────────────────────────────────────────────────────


def test_actuation_ack_failure_failsafe_open():
    relay = FlakyAckRelay(fail_on_close=True)
    act = ActuationListener(
        relay=relay, speaker=NullSpeaker(), enable_watchdog=False
    )
    act.start()
    act.on_result(_result(decision=Decision.ACCEPT))
    assert relay.closed is False
    assert relay.ack_failures >= 1
    act.stop()


def test_actuation_watchdog_forces_open_on_stale_heartbeat():
    relay = NullRelay()
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    def sleep(dt):
        clock["t"] += dt

    wd = ActuationWatchdog(
        relay, timeout_s=0.1, poll_s=0.02, clock=now, sleep=sleep
    )
    act = ActuationListener(
        relay=relay, speaker=NullSpeaker(), watchdog=wd, enable_watchdog=True
    )
    act.start()
    act.on_result(_result(decision=Decision.ACCEPT))
    assert relay.closed is True
    # Stop heartbeats; advance clock past timeout via watchdog loop.
    clock["t"] += 0.5
    # Manually drive one watchdog iteration by letting the thread run briefly.
    deadline = time.time() + 2.0
    while wd.forced_open_count == 0 and time.time() < deadline:
        time.sleep(0.05)
        clock["t"] += 0.05
    assert wd.forced_open_count >= 1
    assert relay.closed is False
    act.stop()


def test_actuation_kill_mid_accept_leaves_watchdog_owner():
    """Simulate process death: listener gone, watchdog alone still opens relay."""
    relay = NullRelay()
    clock = {"t": 100.0}
    wd = ActuationWatchdog(
        relay,
        timeout_s=0.05,
        poll_s=0.01,
        clock=lambda: clock["t"],
        sleep=lambda dt: clock.__setitem__("t", clock["t"] + dt),
    )
    wd.start()
    relay.set_closed(True)
    assert relay.closed is True
    # No further heartbeats (kill -9 of decision process).
    deadline = time.time() + 2.0
    while wd.forced_open_count == 0 and time.time() < deadline:
        time.sleep(0.02)
        clock["t"] += 0.02
    assert relay.closed is False
    wd.stop()


# ── Phase D ──────────────────────────────────────────────────────────────────


def test_integrity_check_fail_closed(tmp_path: Path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    model = store / "risk_gbt.onnx"
    model.write_bytes(b"onnx-bytes-v1")
    policy = tmp_path / "policy.yaml"
    policy.write_text("thresholds: {}\n", encoding="utf-8")

    priv, pub = generate_keypair()
    (store / "integrity_ed25519.pub").write_bytes(dump_public_key(pub))
    manifest = {
        "version": 1,
        "files": {
            "risk_gbt.onnx": __import__("hashlib").sha256(model.read_bytes()).hexdigest(),
            "policy.yaml": __import__("hashlib").sha256(policy.read_bytes()).hexdigest(),
        },
        "meta": {},
    }
    (store / "integrity_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (store / "integrity_manifest.sig").write_bytes(sign_manifest(manifest, priv))

    monkeypatch.setenv("DRIVEAUTH_INTEGRITY_CHECK", "1")
    ok, reason = verify_store_integrity(store, policy_path=policy, public_key=pub)
    assert ok and reason == "ok"

    model.write_bytes(b"tampered")
    with pytest.raises(IntegrityError, match="hash mismatch"):
        verify_store_integrity(store, policy_path=policy, public_key=pub)


def test_integrity_skipped_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DRIVEAUTH_INTEGRITY_CHECK", raising=False)
    ok, reason = verify_store_integrity(tmp_path)
    assert ok and reason == "skipped"


# ── Phase E ──────────────────────────────────────────────────────────────────


def test_enroll_requires_consent(tmp_path: Path):
    from driveauth.enrollment import enroll_driver

    store = tmp_path / "store"
    data = tmp_path / "data" / "driverC"
    store.mkdir()
    (data / "voice" / "enroll").mkdir(parents=True)
    (data / "face" / "enroll").mkdir(parents=True)
    with pytest.raises(ConsentRequiredError):
        require_consent(store, "driverC")
    with pytest.raises(ConsentRequiredError):
        enroll_driver(store, data, "driverC", require_minimums=False)


def test_purge_driver_removes_biometrics(tmp_path: Path):
    store = tmp_path / "store"
    store.mkdir()
    ensure_key(store)
    emb = np.ones(8, dtype=np.float32)
    emb /= np.linalg.norm(emb)
    save_embedding(store, "voices/driverP.enc", emb)
    save_embedding(store, "faces/driverP.enc", emb)
    ood = store / "ood_stats"
    ood.mkdir()
    np.savez(ood / "voice_driverP.npz", mean=emb, std=np.ones_like(emb))
    np.savez(ood / "face_driverP.npz", mean=emb, std=np.ones_like(emb))
    (store / "profiles").mkdir()
    (store / "profiles" / "driverP.json").write_text(
        json.dumps({"driverP": {"driver_id": "driverP"}}), encoding="utf-8"
    )
    record_consent(store, "driverP")
    assert biometric_residue(store, "driverP")

    result = purge_driver(store, "driverP")
    assert result["complete"] is True
    assert biometric_residue(store, "driverP") == []
    # Templates gone — cannot load
    from driveauth.template_store import load_embedding

    assert load_embedding(store, "voices/driverP.enc") is None
    assert load_embedding(store, "faces/driverP.enc") is None


# ── Phase F ──────────────────────────────────────────────────────────────────


def test_ota_rejects_tampered_package(tmp_path: Path):
    priv, pub = generate_keypair()
    pkg = tmp_path / "pkg"
    (pkg / "payload").mkdir(parents=True)
    (pkg / "payload" / "policy.yaml").write_text("a: 1\n", encoding="utf-8")
    files = {
        "policy.yaml": __import__("hashlib")
        .sha256((pkg / "payload" / "policy.yaml").read_bytes())
        .hexdigest()
    }
    manifest = {"version": 1, "version_id": "v1", "files": files, "meta": {}}
    (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg / "manifest.sig").write_bytes(sign_manifest(manifest, priv))

    # Tamper payload after signing.
    (pkg / "payload" / "policy.yaml").write_text("a: 2\n", encoding="utf-8")
    with pytest.raises(OTAError, match="tampered|invalid"):
        verify_update_package(pkg, public_key=pub)


def test_ota_rollback_on_failed_health(tmp_path: Path):
    priv, pub = generate_keypair()
    install = tmp_path / "install"
    install.mkdir()
    # Seed current good version
    current = install / "current"
    current.mkdir()
    (current / "HEALTH_OK").write_text("1", encoding="utf-8")
    (current / "marker").write_text("v1", encoding="utf-8")

    pkg = tmp_path / "pkg"
    (pkg / "payload").mkdir(parents=True)
    (pkg / "payload" / "HEALTH_FAIL").write_text("1", encoding="utf-8")
    (pkg / "payload" / "marker").write_text("v2-bad", encoding="utf-8")
    files = {
        rel: __import__("hashlib").sha256(p.read_bytes()).hexdigest()
        for rel, p in (
            ("HEALTH_FAIL", pkg / "payload" / "HEALTH_FAIL"),
            ("marker", pkg / "payload" / "marker"),
        )
    }
    manifest = {"version": 1, "version_id": "v2", "files": files, "meta": {}}
    (pkg / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pkg / "manifest.sig").write_bytes(sign_manifest(manifest, priv))

    client = OTAClient(install, public_key=pub)
    with pytest.raises(OTAError, match="health"):
        client.apply_package(pkg)
    assert client.last_rollback is True
    assert (install / "current" / "marker").read_text() == "v1"


# ── Phase G ──────────────────────────────────────────────────────────────────


def test_fleet_telemetry_schema_no_biometrics():
    payload = build_telemetry_payload(
        vehicle_id="v1",
        firmware_version="0.2.0",
        accept_count=10,
        reject_count=2,
        step_up_count=1,
        sensor_flags={"voice": True, "face": True, "finger": False},
    )
    assert_no_biometric_content(payload)
    assert payload["schema"] == "driveauth.fleet_telemetry.v1"
    assert "auth" in payload and "sensors" in payload
    for key in FORBIDDEN_KEYS:
        assert key not in payload

    bad = dict(payload)
    bad["embedding"] = [0.1, 0.2]
    with pytest.raises(AssertionError):
        assert_no_biometric_content(bad)


# ── Phase I ──────────────────────────────────────────────────────────────────


def test_score_buckets_for_drift_logging():
    assert score_bucket(0.05) == "0.0-0.2"
    assert score_bucket(0.5) == "0.4-0.6"
    assert score_bucket(0.99) == "0.8-1.0"
    entry_fields_doc = (
        "Phase I logs trust_bucket/risk_bucket/confidence_bucket only — "
        "does not close skin-tone validation"
    )
    assert "does not close" in entry_fields_doc
