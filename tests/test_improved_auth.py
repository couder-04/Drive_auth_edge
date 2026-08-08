"""Improved Auth page + Stage-2 capture helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from dashboard.app import app
from driveauth.enrollment import ensure_driver_layout, save_face_jpeg, save_voice_wav_bytes
from driveauth.improved_auth import (
    auto_generate_face_blur,
    auto_generate_voice_silent,
    improved_auth_status,
    prepare_improved_auth_datasets,
    sync_genuine_from_enroll,
)

ADMIN_HEADERS = {"X-API-Key": "test-dashboard-key"}


def _client():
    c = TestClient(app)
    c.headers.update(ADMIN_HEADERS)
    return c


def _tiny_jpeg() -> bytes:
    import cv2

    img = np.full((120, 120, 3), 100, dtype=np.uint8)
    cv2.circle(img, (60, 55), 35, (180, 160, 140), -1)
    ok, enc = cv2.imencode(".jpg", img)
    assert ok
    return enc.tobytes()


def _tiny_wav(seconds: float = 1.2, sr: int = 16_000) -> bytes:
    import io
    import wave

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


def test_improved_auth_page_renders():
    client = _client()
    r = client.get("/improved-auth")
    assert r.status_code == 200
    assert "Improved Auth" in r.text
    assert "Stays local on the edge" in r.text
    assert "Replay screen" in r.text
    assert "Music + commands" in r.text


def test_auto_blur_and_silent(tmp_path: Path):
    ensure_driver_layout(tmp_path, "drvIA")
    save_face_jpeg(tmp_path, "drvIA", _tiny_jpeg(), split="enroll")
    save_face_jpeg(tmp_path, "drvIA", _tiny_jpeg(), split="enroll")
    save_face_jpeg(tmp_path, "drvIA", _tiny_jpeg(), split="enroll")
    save_voice_wav_bytes(tmp_path, "drvIA", _tiny_wav(), split="enroll")

    blur = auto_generate_face_blur(tmp_path, "drvIA", n=3)
    assert len(blur) >= 3
    silent = auto_generate_voice_silent(tmp_path, "drvIA", n=3)
    assert len(silent) >= 3
    copied = sync_genuine_from_enroll(tmp_path, "drvIA")
    assert copied["face"] >= 1
    assert copied["voice"] >= 1

    store = tmp_path / "store"
    store.mkdir()
    st = improved_auth_status(tmp_path, store, "drvIA")
    assert st["face"]["attack_blur"] >= 3
    assert st["voice"]["attack_silent"] >= 3


def test_improved_auth_upload_api(tmp_path: Path, monkeypatch):
    import dashboard.app as app_mod

    store = tmp_path / "store"
    store.mkdir()
    (store / "faces").mkdir()
    (store / "voices").mkdir()
    (store / "faces" / "drvUp.enc").write_bytes(b"x")
    (store / "voices" / "drvUp.enc").write_bytes(b"x")
    monkeypatch.setattr(app_mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_register_store", lambda: store)
    monkeypatch.setattr(app_mod, "_unified_store", lambda: store)

    ensure_driver_layout(tmp_path, "drvUp")
    for _ in range(3):
        save_face_jpeg(tmp_path, "drvUp", _tiny_jpeg(), split="enroll")
        save_voice_wav_bytes(tmp_path, "drvUp", _tiny_wav(), split="enroll")

    client = _client()
    r = client.post(
        "/api/improved-auth/face",
        data={"driver_id": "drvUp", "split": "attack_side"},
        files={"file": ("a.jpg", _tiny_jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["face"]["attack_side"] == 1

    r = client.post(
        "/api/improved-auth/voice",
        data={"driver_id": "drvUp", "split": "noisy"},
        files={"file": ("a.wav", _tiny_wav(), "audio/wav")},
    )
    assert r.status_code == 200
    assert r.json()["voice"]["noisy"] == 1

    r = client.post(
        "/api/improved-auth/auto-fill",
        json={"driver_id": "drvUp"},
    )
    assert r.status_code == 200
    assert r.json()["face"]["attack_blur"] >= 3

    r = client.get("/api/improved-auth/status", params={"driver_id": "drvUp"})
    assert r.status_code == 200
    assert r.json()["driver_id"] == "drvUp"


def test_prepare_datasets(tmp_path: Path):
    ensure_driver_layout(tmp_path, "drvPrep")
    for _ in range(3):
        save_face_jpeg(tmp_path, "drvPrep", _tiny_jpeg(), split="enroll")
        save_voice_wav_bytes(tmp_path, "drvPrep", _tiny_wav(), split="enroll")
    out = prepare_improved_auth_datasets(tmp_path, "drvPrep")
    assert len(out["blur_paths"]) >= 3
    assert len(out["silent_paths"]) >= 3
