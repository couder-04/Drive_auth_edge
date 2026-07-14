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
    assert st["ready_to_register"] is False


def test_register_api_init_and_uploads(tmp_path: Path, monkeypatch) -> None:
    import dashboard.app as app_mod

    monkeypatch.setattr(app_mod, "_DATA_ROOT", tmp_path)
    monkeypatch.setattr(app_mod, "_REGISTER_STORE", str(tmp_path / "store"))

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
