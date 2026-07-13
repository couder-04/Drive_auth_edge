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

from driveauth.matchers.face import FaceMatcher  # noqa: E402
from driveauth.matchers.voice import VoiceMatcher  # noqa: E402
from driveauth.ood_detector import OODDetector  # noqa: E402
from driveauth.template_store import ensure_key, save_embedding  # noqa: E402


def _load_wav(path: Path, sr: int = 16_000) -> np.ndarray:
    try:
        import wave

        with wave.open(str(path), "rb") as w:
            assert w.getnchannels() in (1, 2)
            frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if w.getnchannels() == 2:
                audio = audio.reshape(-1, 2).mean(axis=1)
            if w.getframerate() != sr:
                # crude resample
                ratio = sr / w.getframerate()
                idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
                idx = np.clip(idx, 0, len(audio) - 1)
                audio = audio[idx]
            return audio.astype(np.float32)
    except Exception:
        import soundfile as sf  # type: ignore

        audio, file_sr = sf.read(str(path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if file_sr != sr:
            ratio = sr / file_sr
            idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        return audio.astype(np.float32)


def _mean_embed_voice(store: Path, wavs: list[Path], driver_id: str) -> np.ndarray:
    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))
    if vm._model is None:
        raise RuntimeError("ECAPA not loaded — run phase2a_setup.py first")
    embs = []
    for p in wavs:
        audio = _load_wav(p)
        emb = vm.embed(audio)
        if emb is not None:
            embs.append(emb)
            print(f"  voice ok: {p.name}")
        else:
            print(f"  voice skip: {p.name}")
    if not embs:
        raise RuntimeError("no voice embeddings produced")
    mean = np.mean(np.stack(embs), axis=0).astype(np.float32)
    save_embedding(store, f"voices/{driver_id}.enc", mean)
    return mean


def _mean_embed_face(store: Path, images: list[Path], driver_id: str) -> np.ndarray:
    import cv2  # type: ignore

    fm = FaceMatcher.load(str(store), driver_id)
    if fm._session is None:
        raise RuntimeError("Face ONNX not loaded — run phase2a_setup.py first")
    embs = []
    for p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            print(f"  face skip (unreadable): {p.name}")
            continue
        emb = fm.embed_bgr(bgr)
        if emb is not None:
            embs.append(emb)
            print(f"  face ok: {p.name}")
        else:
            print(f"  face skip: {p.name}")
    if not embs:
        raise RuntimeError("no face embeddings produced")
    mean = np.mean(np.stack(embs), axis=0).astype(np.float32)
    save_embedding(store, f"faces/{driver_id}.enc", mean)
    return mean


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
        # crude oval "face" so cascade/center-crop has structure
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
        help="Generate synthetic enroll samples if folders are empty (smoke test)",
    )
    args = parser.parse_args()

    store = Path(args.store)
    data = Path(args.data)
    ensure_key(store)

    voice_dir = data / "voice" / "enroll"
    face_dir = data / "face" / "enroll"
    wavs = sorted(
        list(voice_dir.glob("*.wav"))
        + list(voice_dir.glob("*.flac"))
        + list(voice_dir.glob("*.mp3"))
    )
    images = sorted(
        list(face_dir.glob("*.jpg"))
        + list(face_dir.glob("*.jpeg"))
        + list(face_dir.glob("*.png"))
    )

    if args.synthetic or not wavs:
        if not wavs:
            print("No voice enroll WAVs — generating synthetic samples")
            wavs = _synthetic_voice_wavs(data)
    if args.synthetic or not images:
        if not images:
            print("No face enroll images — generating synthetic samples")
            images = _synthetic_face_images(data)

    print("Enrolling voice from", len(wavs), "files")
    v_emb = _mean_embed_voice(store, wavs, args.driver_id)
    print("Enrolling face from", len(images), "files")
    f_emb = _mean_embed_face(store, images, args.driver_id)

    OODDetector.seed_baselines(
        str(store),
        args.driver_id,
        voice_dim=int(v_emb.shape[0]),
        face_dim=int(f_emb.shape[0]),
        finger_dim=64,
    )
    # Overwrite means with real enrollment embeddings for tighter OOD later
    ood_dir = store / "ood_stats"
    np.savez(
        ood_dir / f"voice_{args.driver_id}.npz",
        mean=v_emb,
        std=np.ones_like(v_emb) * 0.5,
    )
    np.savez(
        ood_dir / f"face_{args.driver_id}.npz",
        mean=f_emb,
        std=np.ones_like(f_emb) * 0.5,
    )

    print("\nEnrollment complete:")
    print(f"  {store}/voices/{args.driver_id}.enc")
    print(f"  {store}/faces/{args.driver_id}.enc")
    print("  OOD baselines updated")
    print(f"\nNext: python scripts/phase2a_demo.py --store {store}")


if __name__ == "__main__":
    main()
