"""Driver registration API — folder layout + sample persistence."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from driveauth.enrollment import (
    ensure_driver_layout,
    enrollment_status,
    list_enroll_images,
    list_enroll_wavs,
    save_face_jpeg,
    save_voice_wav_bytes,
    validate_driver_id,
)


def _tiny_wav_bytes(seconds: float = 0.5, sr: int = 16_000) -> bytes:
    n = int(sr * seconds)
    t = np.linspace(0, seconds, n, dtype=np.float32)
    sig = (0.2 * np.sin(2 * np.pi * 220 * t) * 20000).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(sig.tobytes())
    return buf.getvalue()


def _tiny_jpeg_bytes() -> bytes:
    # Minimal valid-ish JPEG header + padding (OpenCV may not decode; file I/O only)
    # Use a real tiny JPEG encoded with numpy/pil-free approach via OpenCV if present.
    try:
        import cv2

        img = np.full((64, 64, 3), 120, dtype=np.uint8)
        ok, enc = cv2.imencode(".jpg", img)
        assert ok
        return enc.tobytes()
    except Exception:
        # Fallback: still exercise write path with arbitrary bytes labeled jpg
        return b"\xff\xd8\xff\xe0" + b"\x00" * 200 + b"\xff\xd9"


def test_validate_driver_id() -> None:
    assert validate_driver_id("driver2") == "driver2"
    try:
        validate_driver_id("../etc")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_save_samples_into_driver_folder(tmp_path: Path) -> None:
    ensure_driver_layout(tmp_path, "driverX")
    face = save_face_jpeg(tmp_path, "driverX", _tiny_jpeg_bytes())
    voice = save_voice_wav_bytes(tmp_path, "driverX", _tiny_wav_bytes())
    assert face.exists()
    assert voice.exists()
    assert face.parent.name == "enroll"
    assert voice.parent.name == "enroll"
    assert len(list_enroll_images(tmp_path / "driverX")) == 1
    assert len(list_enroll_wavs(tmp_path / "driverX")) == 1
    st = enrollment_status(tmp_path, tmp_path / "store", "driverX")
    assert st["face_count"] == 1
    assert st["voice_count"] == 1
    assert st["home_set"] is False
    assert st["ready_to_register"] is False


def test_ready_to_register_requires_home(tmp_path: Path) -> None:
    from driveauth.enrollment import MIN_FACE_ENROLL, MIN_VOICE_ENROLL
    from driveauth.profile_store import ProfileStore

    store = tmp_path / "store"
    store.mkdir()
    ensure_driver_layout(tmp_path, "driverHome")
    for _ in range(MIN_FACE_ENROLL):
        save_face_jpeg(tmp_path, "driverHome", _tiny_jpeg_bytes())
    for _ in range(MIN_VOICE_ENROLL):
        save_voice_wav_bytes(tmp_path, "driverHome", _tiny_wav_bytes())
    st = enrollment_status(tmp_path, store, "driverHome")
    assert st["samples_ready"] is True
    assert st["home_set"] is False
    assert st["ready_to_register"] is False

    ProfileStore(store / "profiles" / "driverHome.json", "driverHome").set_home(
        12.97, 77.59
    )
    st2 = enrollment_status(tmp_path, store, "driverHome")
    assert st2["home_set"] is True
    assert st2["ready_to_register"] is True


def test_register_complete_rejects_without_home(tmp_path: Path, monkeypatch) -> None:
    import dashboard.app as app_mod

    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(app_mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_register_store", lambda: store)
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    client = TestClient(app)
    client.post("/api/register/init", json={"driver_id": "noHome"})
    r = client.post("/api/register/complete", json={"driver_id": "noHome"})
    assert r.status_code == 400
    assert "home" in r.json()["detail"].lower()


def test_enrolled_driver_is_locked_from_mutation(tmp_path: Path, monkeypatch) -> None:
    import dashboard.app as app_mod
    from driveauth.template_store import ensure_key

    store = tmp_path / "store"
    store.mkdir()
    ensure_key(store)
    (store / "faces").mkdir()
    (store / "voices").mkdir()
    (store / "faces" / "driverLock.enc").write_bytes(b"x")
    (store / "voices" / "driverLock.enc").write_bytes(b"x")
    monkeypatch.setattr(app_mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_register_store", lambda: store)
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    client = TestClient(app)
    st = client.get("/api/register/status", params={"driver_id": "driverLock"})
    assert st.status_code == 200
    assert st.json()["locked"] is True

    r = client.post(
        "/api/register/face",
        data={"driver_id": "driverLock"},
        files={"file": ("a.jpg", _tiny_jpeg_bytes(), "image/jpeg")},
    )
    assert r.status_code == 403
    assert "locked" in r.json()["detail"].lower()

    r = client.post("/api/register/clear", json={"driver_id": "driverLock"})
    assert r.status_code == 403

    r = client.post(
        "/api/register/home",
        json={"driver_id": "driverLock", "lat": 12.9, "lon": 77.5},
    )
    assert r.status_code == 403


def test_register_api_init_and_uploads(tmp_path: Path, monkeypatch) -> None:
    import dashboard.app as app_mod

    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(app_mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_register_store", lambda: store)
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    client = TestClient(app)
    r = client.post("/api/register/init", json={"driver_id": "driverNew"})
    assert r.status_code == 200
    assert (tmp_path / "driverNew" / "face" / "enroll").is_dir()

    r = client.post(
        "/api/register/face",
        data={"driver_id": "driverNew"},
        files={"file": ("a.jpg", _tiny_jpeg_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["face_count"] == 1

    r = client.post(
        "/api/register/voice",
        data={"driver_id": "driverNew"},
        files={"file": ("a.wav", _tiny_wav_bytes(), "audio/wav")},
    )
    assert r.status_code == 200
    assert r.json()["voice_count"] == 1

    r = client.get("/register")
    assert r.status_code == 200
    assert "Register a driver" in r.text
    assert "Registered drivers" in r.text

    r = client.get("/api/register/drivers")
    assert r.status_code == 200
    ids = {row["driver_id"] for row in r.json()}
    assert "driverNew" in ids

    r = client.get("/manual")
    assert r.status_code == 200
    assert "mode-manual" in r.text
    r = client.get("/standalone")
    assert r.status_code == 200
    assert "mode-standalone" in r.text
    assert "Pay · standalone" in r.text
    assert "Face locked" in r.text
    assert "Location (required)" in r.text


def test_pipeline_next_unlock_voice_only(tmp_path: Path, monkeypatch) -> None:
    """Voice miss with face locked should pause at escalate — not light face."""
    from driveauth.types import Decision, DriveAuthResult

    import dashboard.app as app_mod

    result = DriveAuthResult(
        decision=Decision.REJECT,
        trust_score=0.4,
        risk_score=0.1,
        confidence_score=0.8,
        tier="standard",
        explanations=[
            "escalation_voice_face_finger_ladder",
            "ladder_accept_bar_voice_0.720",
            "ladder_escalate_after_voice_score_0.400",
            "probed_voice",
            "ladder_exhausted_reject",
        ],
        modality_scores={"voice": {"score": 0.4, "available": True}},
        amount=50.0,
        currency="INR",
        beneficiary="Mom",
        action="pay",
    )
    pipe = app_mod._pipeline_trace(result)
    assert pipe["probed"] == ["voice"]
    assert pipe["next_unlock"] == "face"
    assert pipe["pause_after"] == "ladder"
    voice_rung = next(r for r in pipe["stages"][3]["rungs"] if r["id"] == "voice")
    face_rung = next(r for r in pipe["stages"][3]["rungs"] if r["id"] == "face")
    finger_rung = next(r for r in pipe["stages"][3]["rungs"] if r["id"] == "finger")
    assert voice_rung["status"] == "escalate"
    assert face_rung["status"] == "locked"
    assert finger_rung["status"] == "locked"
    assert pipe["stages"][3]["status"] == "stepup"
    assert pipe["stages"][4]["status"] == "hold"  # policy paused
    assert pipe["stages"][5]["status"] == "hold"  # decision paused


def test_pipeline_next_unlock_face_stops_before_finger() -> None:
    from driveauth.types import Decision, DriveAuthResult

    import dashboard.app as app_mod

    result = DriveAuthResult(
        decision=Decision.REJECT,
        trust_score=0.3,
        risk_score=0.1,
        confidence_score=0.7,
        tier="standard",
        explanations=[
            "escalation_voice_face_finger_ladder",
            "ladder_escalate_after_voice_score_0.400",
            "ladder_escalate_after_face_score_0.350",
            "probed_voice+face",
            "ladder_exhausted_reject",
        ],
        modality_scores={
            "voice": {"score": 0.4, "available": True},
            "face": {"score": 0.35, "available": True},
        },
        amount=50.0,
        currency="INR",
        beneficiary="Mom",
        action="pay",
    )
    pipe = app_mod._pipeline_trace(result)
    assert pipe["probed"] == ["voice", "face"]
    assert pipe["next_unlock"] == "finger"
    assert pipe["pause_after"] == "ladder"
    rungs = {r["id"]: r for r in pipe["stages"][3]["rungs"]}
    assert rungs["voice"]["status"] == "escalate"
    assert rungs["face"]["status"] == "escalate"
    assert rungs["finger"]["status"] == "locked"
