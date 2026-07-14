#!/usr/bin/env python3
"""Phase 2a — enroll voice/face templates from data/driver1 into the store.

Usage:
  python scripts/phase2a_enroll.py --store ./driveauth_store_phase2a
  python scripts/phase2a_enroll.py --store ./driveauth_store_phase2a --synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.enrollment import (  # noqa: E402
    enroll_driver,
    list_enroll_images,
    list_enroll_wavs,
)
from driveauth.template_store import ensure_key  # noqa: E402


def _synthetic_voice_wavs(data_dir: Path, n: int = 5) -> list[Path]:
    """Generate speech-like WAVs so Phase 2a can smoke-test without mic capture."""
    import wave

    out_dir = data_dir / "voice" / "enroll"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    sr = 16_000
    for i in range(n):
        path = out_dir / f"synth_enroll_{i:02d}.wav"
        t = np.linspace(0, 2.0, sr * 2, dtype=np.float32)
        rng = np.random.default_rng(10 + i)
        env = 0.05 + 0.2 * (0.5 + 0.5 * np.sin(2 * np.pi * (2 + i * 0.3) * t))
        sig = env * np.sin(2 * np.pi * (160 + i * 20) * t)
        sig += 0.01 * rng.standard_normal(sig.shape[0]).astype(np.float32)
        pcm = np.clip(sig * 20000, -32767, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        paths.append(path)
    return paths


def _synthetic_face_images(data_dir: Path, n: int = 5) -> list[Path]:
    import cv2  # type: ignore

    out_dir = data_dir / "face" / "enroll"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        path = out_dir / f"synth_enroll_{i:02d}.jpg"
        img = np.full((240, 240, 3), 40, dtype=np.uint8)
        cv2.ellipse(img, (120, 120), (70, 90), 0, 0, 360, (180, 160, 140), -1)
        cv2.circle(img, (95, 100), 8, (20, 20, 20), -1)
        cv2.circle(img, (145, 100), 8, (20, 20, 20), -1)
        cv2.ellipse(img, (120, 150), (25, 12), 0, 0, 180, (80, 60, 60), 2)
        noise = (np.random.default_rng(i).random(img.shape) * 15).astype(np.uint8)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        cv2.imwrite(str(path), img)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2a enrollment")
    parser.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    parser.add_argument("--data", default=str(ROOT / "data" / "driver1"))
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="ONLY for smoke tests: generate blob face/voice samples if folders are empty",
    )
    args = parser.parse_args()

    store = Path(args.store)
    data = Path(args.data)
    ensure_key(store)

    wavs = list_enroll_wavs(data)
    images = list_enroll_images(data)

    if args.synthetic:
        if not wavs:
            print("No voice enroll WAVs — generating synthetic samples (--synthetic)")
            wavs = _synthetic_voice_wavs(data)
        if not images:
            print("No face enroll images — generating synthetic samples (--synthetic)")
            images = _synthetic_face_images(data)
    else:
        missing: list[str] = []
        if not wavs:
            missing.append(f"voice WAVs in {data / 'voice' / 'enroll'}")
        if not images:
            missing.append(f"face images in {data / 'face' / 'enroll'}")
        if missing:
            print("Missing enroll samples (refusing to invent synthetic data):")
            for item in missing:
                print(f"  - {item}")
            print(
                "\nCapture real samples via the dashboard register UI "
                "(driveauth-dashboard → /register), or pass --synthetic for a smoke test only."
            )
            raise SystemExit(1)

        # Refuse to enroll leftover smoke-test blobs as if they were a real identity.
        synth_faces = [p for p in images if p.name.startswith("synth_")]
        synth_wavs = [p for p in wavs if p.name.startswith("synth_")]
        if synth_faces or synth_wavs:
            print("Found synthetic enroll files — remove them before real enrollment:")
            for path in synth_faces + synth_wavs:
                print(f"  - {path}")
            print("\nOr re-run with --synthetic if you truly want a smoke-test template.")
            raise SystemExit(1)

    print("Enrolling voice from", len(list_enroll_wavs(data)), "files")
    print("Enrolling face from", len(list_enroll_images(data)), "files")
    result = enroll_driver(store, data, args.driver_id, require_minimums=False)
    print("\nEnrollment complete:")
    print(f"  {store}/{result['voice_template']}")
    print(f"  {store}/{result['face_template']}")
    print("  OOD baselines updated")
    print(f"\nNext: python scripts/phase2a_demo.py --store {store}")


if __name__ == "__main__":
    main()
