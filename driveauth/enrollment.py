"""Shared Phase 2a voice/face enrollment from on-disk samples."""

from __future__ import annotations

import logging
import re
import wave
from pathlib import Path

import numpy as np

from driveauth.matchers.face import FaceMatcher
from driveauth.matchers.voice import VoiceMatcher
from driveauth.ood_detector import OODDetector
from driveauth.profile_store import ProfileStore
from driveauth.key_protection import KeyProtector, SoftwareKeyProtector
from driveauth.template_store import TemplateStore, ensure_key, save_embedding

logger = logging.getLogger("driveauth.enrollment")

DRIVER_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$")

VOICE_SUBDIRS = (
    "enroll",
    "genuine",
    "attack_replay",
    "attack_silent",
    "attack_other_speaker",
    "noisy",
)
FACE_SUBDIRS = (
    "enroll",
    "genuine",
    "attack_blur",
    "attack_side",
    "attack_replay_screen",
)

MIN_FACE_ENROLL = 5
MIN_VOICE_ENROLL = 5


def validate_driver_id(driver_id: str) -> str:
    cleaned = (driver_id or "").strip()
    if not DRIVER_ID_RE.match(cleaned):
        raise ValueError(
            "driver_id must start with a letter and use only "
            "letters, digits, _ or - (max 32 chars)"
        )
    return cleaned


def driver_data_root(data_root: str | Path, driver_id: str) -> Path:
    return Path(data_root) / validate_driver_id(driver_id)


def ensure_driver_layout(data_root: str | Path, driver_id: str) -> Path:
    """Create Phase 3 folder layout under data/<driver_id>/."""
    root = driver_data_root(data_root, driver_id)
    for name in VOICE_SUBDIRS:
        (root / "voice" / name).mkdir(parents=True, exist_ok=True)
    for name in FACE_SUBDIRS:
        (root / "face" / name).mkdir(parents=True, exist_ok=True)
    (root / "finger" / "enroll").mkdir(parents=True, exist_ok=True)
    (root / "behavioral").mkdir(parents=True, exist_ok=True)
    (root / "transaction").mkdir(parents=True, exist_ok=True)
    return root


def list_enroll_wavs(driver_dir: Path) -> list[Path]:
    voice_dir = driver_dir / "voice" / "enroll"
    if not voice_dir.is_dir():
        return []
    return sorted(
        list(voice_dir.glob("*.wav"))
        + list(voice_dir.glob("*.flac"))
        + list(voice_dir.glob("*.mp3"))
    )


def list_enroll_images(driver_dir: Path) -> list[Path]:
    face_dir = driver_dir / "face" / "enroll"
    if not face_dir.is_dir():
        return []
    return sorted(
        list(face_dir.glob("*.jpg"))
        + list(face_dir.glob("*.jpeg"))
        + list(face_dir.glob("*.png"))
    )


def next_enroll_index(directory: Path, prefix: str, suffix: str) -> int:
    existing = list(directory.glob(f"{prefix}_*.{suffix}"))
    nums: list[int] = []
    for path in existing:
        stem = path.stem  # enroll_01
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            nums.append(int(parts[1]))
    return (max(nums) + 1) if nums else 1


def save_face_jpeg(
    data_root: str | Path,
    driver_id: str,
    jpeg_bytes: bytes,
    *,
    split: str = "enroll",
) -> Path:
    root = ensure_driver_layout(data_root, driver_id)
    out_dir = root / "face" / split
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = next_enroll_index(out_dir, split, "jpg")
    path = out_dir / f"{split}_{idx:02d}.jpg"
    path.write_bytes(jpeg_bytes)
    return path


def save_voice_wav_bytes(
    data_root: str | Path,
    driver_id: str,
    wav_bytes: bytes,
    *,
    split: str = "enroll",
) -> Path:
    """Persist a client-produced WAV (any rate/channels) as 16 kHz mono."""
    root = ensure_driver_layout(data_root, driver_id)
    out_dir = root / "voice" / split
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = next_enroll_index(out_dir, split, "wav")
    path = out_dir / f"{split}_{idx:02d}.wav"

    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as src:
        n_channels = src.getnchannels()
        sampwidth = src.getsampwidth()
        framerate = src.getframerate()
        n_frames = src.getnframes()
        raw = src.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError("expected 16-bit PCM WAV")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    target_sr = 16_000
    if framerate != target_sr and len(audio) > 0:
        ratio = target_sr / float(framerate)
        idx_map = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
        idx_map = np.clip(idx_map, 0, len(audio) - 1)
        audio = audio[idx_map]
    pcm = np.clip(audio, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(target_sr)
        dst.writeframes(pcm.tobytes())
    return path


def _load_wav(path: Path, sr: int = 16_000) -> np.ndarray:
    try:
        with wave.open(str(path), "rb") as w:
            assert w.getnchannels() in (1, 2)
            frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            if w.getnchannels() == 2:
                audio = audio.reshape(-1, 2).mean(axis=1)
            if w.getframerate() != sr:
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


def mean_embed_voice(
    store: Path,
    wavs: list[Path],
    driver_id: str,
    *,
    protector: KeyProtector | None = None,
) -> np.ndarray:
    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))
    if vm._model is None:
        raise RuntimeError("ECAPA not loaded — run phase2a_setup.py first")
    embs = []
    for p in wavs:
        audio = _load_wav(p)
        emb = vm.embed(audio)
        if emb is not None:
            embs.append(emb)
            logger.info("voice ok: %s", p.name)
        else:
            logger.warning("voice skip: %s", p.name)
    if not embs:
        raise RuntimeError("no voice embeddings produced")
    mean = np.mean(np.stack(embs), axis=0).astype(np.float32)
    save_embedding(store, f"voices/{driver_id}.enc", mean, protector=protector)
    return mean


def mean_embed_face(
    store: Path,
    images: list[Path],
    driver_id: str,
    *,
    protector: KeyProtector | None = None,
) -> np.ndarray:
    import cv2  # type: ignore

    fm = FaceMatcher.load(str(store), driver_id)
    if fm._session is None:
        raise RuntimeError("Face ONNX not loaded — run phase2a_setup.py first")
    embs = []
    for p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            logger.warning("face skip (unreadable): %s", p.name)
            continue
        emb = fm.embed_bgr(bgr)
        if emb is not None:
            embs.append(emb)
            logger.info("face ok: %s", p.name)
        else:
            logger.warning("face skip: %s", p.name)
    if not embs:
        raise RuntimeError("no face embeddings produced")
    mean = np.mean(np.stack(embs), axis=0).astype(np.float32)
    save_embedding(store, f"faces/{driver_id}.enc", mean, protector=protector)
    return mean


def list_registered_drivers(
    data_root: str | Path,
    store_dir: str | Path,
) -> list[dict]:
    """Union of data/<id>/ folders and store face/voice templates."""
    data_root = Path(data_root)
    store = Path(store_dir)
    ids: set[str] = set()
    if data_root.is_dir():
        for p in data_root.iterdir():
            if p.is_dir() and DRIVER_ID_RE.match(p.name):
                ids.add(p.name)
    faces = store / "faces"
    voices = store / "voices"
    if faces.is_dir():
        ids.update(p.stem for p in faces.glob("*.enc"))
    if voices.is_dir():
        ids.update(p.stem for p in voices.glob("*.enc"))

    rows: list[dict] = []
    for did in sorted(ids):
        st = enrollment_status(data_root, store, did)
        voice_t = bool(st["templates"]["voice"])
        face_t = bool(st["templates"]["face"])
        if voice_t and face_t:
            status = "enrolled"
            status_label = "Enrolled (voice + face)"
        elif voice_t or face_t:
            status = "partial_templates"
            parts = []
            if voice_t:
                parts.append("voice")
            if face_t:
                parts.append("face")
            status_label = "Partial templates · " + " + ".join(parts)
        elif st["samples_ready"] and not st["home_set"]:
            status = "need_home"
            status_label = "Samples ready · pin home to enroll"
        elif st["ready_to_register"]:
            status = "ready_to_enroll"
            status_label = "Ready to enroll · home set"
        elif st["face_count"] or st["voice_count"]:
            status = "capturing"
            status_label = (
                f"Capturing · face {st['face_count']}/{st['min_face']} · "
                f"voice {st['voice_count']}/{st['min_voice']}"
            )
        else:
            status = "empty"
            status_label = "No samples yet"
        rows.append(
            {
                "driver_id": did,
                "name": did,
                "status": status,
                "status_label": status_label,
                "face_count": st["face_count"],
                "voice_count": st["voice_count"],
                "min_face": st["min_face"],
                "min_voice": st["min_voice"],
                "templates": st["templates"],
                "ready_to_register": st["ready_to_register"],
                "home_set": st["home_set"],
                "home_lat": st["home_lat"],
                "home_lon": st["home_lon"],
                "locked": st["locked"],
            }
        )
    return rows


def enrollment_status(
    data_root: str | Path,
    store_dir: str | Path,
    driver_id: str,
) -> dict:
    driver_id = validate_driver_id(driver_id)
    root = Path(data_root) / driver_id
    store = Path(store_dir)
    wavs = list_enroll_wavs(root) if root.exists() else []
    images = list_enroll_images(root) if root.exists() else []
    face_model = (
        (store / "models" / "mobilefacenet.onnx").exists()
        or (store / "mobilefacenet.onnx").exists()
        or (store / "mobilefacenet_int8.onnx").exists()
    )
    voice_model = (store / "models" / "ecapa_voxceleb").is_dir() or (
        store / "enroll" / "pretrained_models" / "ecapa_voxceleb"
    ).is_dir()
    profile = ProfileStore(store / "profiles" / f"{driver_id}.json", driver_id)
    home_lat, home_lon, home_n = profile.home_coords()
    home_set = home_lat is not None and home_lon is not None and home_n >= 1
    samples_ready = (
        len(images) >= MIN_FACE_ENROLL and len(wavs) >= MIN_VOICE_ENROLL
    )
    templates = {
        "voice": (store / "voices" / f"{driver_id}.enc").exists(),
        "face": (store / "faces" / f"{driver_id}.enc").exists(),
    }
    locked = bool(templates["voice"] and templates["face"])
    return {
        "driver_id": driver_id,
        "data_dir": str(root),
        "store_dir": str(store),
        "face_count": len(images),
        "voice_count": len(wavs),
        "face_files": [p.name for p in images],
        "voice_files": [p.name for p in wavs],
        "min_face": MIN_FACE_ENROLL,
        "min_voice": MIN_VOICE_ENROLL,
        "samples_ready": samples_ready,
        "home_lat": home_lat,
        "home_lon": home_lon,
        "home_n": home_n,
        "home_set": home_set,
        # Enrolled drivers cannot be re-captured / cleared from /register.
        "locked": locked,
        "ready_to_register": (not locked) and samples_ready and home_set,
        "face_model_present": face_model,
        "voice_model_present": voice_model,
        "templates": templates,
    }


def enroll_driver(
    store_dir: str | Path,
    data_dir: str | Path,
    driver_id: str,
    *,
    require_minimums: bool = True,
    key_protector: KeyProtector | None = None,
) -> dict:
    """Embed enroll samples and write encrypted templates + OOD baselines.

    ``key_protector`` defaults to :class:`SoftwareKeyProtector` (Fernet key
    on disk, unchanged). Pass a TPM-backed protector to seal the Fernet key.
    """
    driver_id = validate_driver_id(driver_id)
    store = Path(store_dir)
    data = Path(data_dir)
    protector = key_protector or SoftwareKeyProtector()
    TemplateStore(store, protector=protector).ensure_key()

    wavs = list_enroll_wavs(data)
    images = list_enroll_images(data)
    if require_minimums:
        if len(wavs) < MIN_VOICE_ENROLL:
            raise RuntimeError(
                f"need ≥{MIN_VOICE_ENROLL} voice enroll clips, found {len(wavs)}"
            )
        if len(images) < MIN_FACE_ENROLL:
            raise RuntimeError(
                f"need ≥{MIN_FACE_ENROLL} face enroll images, found {len(images)}"
            )
    if not wavs:
        raise RuntimeError("no voice enroll WAVs")
    if not images:
        raise RuntimeError("no face enroll images")

    v_emb = mean_embed_voice(store, wavs, driver_id, protector=protector)
    f_emb = mean_embed_face(store, images, driver_id, protector=protector)

    OODDetector.seed_baselines(
        str(store),
        driver_id,
        voice_dim=int(v_emb.shape[0]),
        face_dim=int(f_emb.shape[0]),
        finger_dim=64,
    )
    ood_dir = store / "ood_stats"
    np.savez(
        ood_dir / f"voice_{driver_id}.npz",
        mean=v_emb,
        std=np.ones_like(v_emb) * 0.5,
    )
    np.savez(
        ood_dir / f"face_{driver_id}.npz",
        mean=f_emb,
        std=np.ones_like(f_emb) * 0.5,
    )
    return {
        "driver_id": driver_id,
        "voice_samples": len(wavs),
        "face_samples": len(images),
        "voice_template": f"voices/{driver_id}.enc",
        "face_template": f"faces/{driver_id}.enc",
        "store_dir": str(store),
        "data_dir": str(data),
        "key_protector": type(protector).__name__,
    }
