"""Stage-2 improved-auth capture helpers (attack sets + auto blur/silent)."""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np

from driveauth.enrollment import (
    ensure_driver_layout,
    list_enroll_images,
    list_enroll_wavs,
    next_enroll_index,
    validate_driver_id,
)
from driveauth.stage2_artifacts import (
    FACE_CALIBRATOR,
    FACE_PAD,
    VOICE_CALIBRATOR,
    resolve_bio_artifact,
)

FACE_USER_SPLITS = ("attack_replay_screen", "attack_side")
FACE_AUTO_SPLIT = "attack_blur"
VOICE_USER_SPLITS = ("attack_replay", "noisy", "attack_other_speaker")
VOICE_AUTO_SPLIT = "attack_silent"

# Soft targets for the UI (trainers need both classes + ≥6 rows).
MIN_PER_USER_BOX = 3
MIN_AUTO_SAMPLES = 3


def _count_images(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return len(
        list(folder.glob("*.jpg"))
        + list(folder.glob("*.jpeg"))
        + list(folder.glob("*.png"))
    )


def _count_wavs(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return len(list(folder.glob("*.wav")))


def _list_names(folder: Path, patterns: tuple[str, ...]) -> list[str]:
    if not folder.is_dir():
        return []
    names: list[str] = []
    for pat in patterns:
        names.extend(p.name for p in sorted(folder.glob(pat)))
    return names


def improved_auth_status(
    data_root: str | Path,
    store_dir: str | Path,
    driver_id: str,
) -> dict:
    driver_id = validate_driver_id(driver_id)
    root = ensure_driver_layout(data_root, driver_id)
    store = Path(store_dir)

    face = {
        "enroll": _count_images(root / "face" / "enroll"),
        "genuine": _count_images(root / "face" / "genuine"),
        "attack_replay_screen": _count_images(root / "face" / "attack_replay_screen"),
        "attack_side": _count_images(root / "face" / "attack_side"),
        "attack_blur": _count_images(root / "face" / "attack_blur"),
    }
    voice = {
        "enroll": _count_wavs(root / "voice" / "enroll"),
        "genuine": _count_wavs(root / "voice" / "genuine"),
        "attack_replay": _count_wavs(root / "voice" / "attack_replay"),
        "noisy": _count_wavs(root / "voice" / "noisy"),
        "attack_other_speaker": _count_wavs(root / "voice" / "attack_other_speaker"),
        "attack_silent": _count_wavs(root / "voice" / "attack_silent"),
    }

    templates = {
        "face": (store / "faces" / f"{driver_id}.enc").exists(),
        "voice": (store / "voices" / f"{driver_id}.enc").exists(),
    }
    stage2 = {}
    for art in (FACE_PAD, FACE_CALIBRATOR, VOICE_CALIBRATOR):
        ref = resolve_bio_artifact(store, driver_id, art)
        stage2[art] = {
            "present": ref.exists,
            "source": ref.source,
            "relpath": ref.relpath,
        }

    face_user_ok = all(face[s] >= MIN_PER_USER_BOX for s in FACE_USER_SPLITS)
    voice_user_ok = all(voice[s] >= MIN_PER_USER_BOX for s in VOICE_USER_SPLITS)
    has_bonafide_face = face["enroll"] + face["genuine"] >= MIN_PER_USER_BOX
    has_bonafide_voice = voice["enroll"] + voice["genuine"] >= MIN_PER_USER_BOX
    ready_to_train = bool(
        templates["face"]
        and templates["voice"]
        and face_user_ok
        and voice_user_ok
        and has_bonafide_face
        and has_bonafide_voice
    )

    return {
        "driver_id": driver_id,
        "data_dir": str(root),
        "min_per_box": MIN_PER_USER_BOX,
        "face": face,
        "voice": voice,
        "face_files": {
            s: _list_names(root / "face" / s, ("*.jpg", "*.jpeg", "*.png"))
            for s in (*FACE_USER_SPLITS, FACE_AUTO_SPLIT, "enroll", "genuine")
        },
        "voice_files": {
            s: _list_names(root / "voice" / s, ("*.wav",))
            for s in (*VOICE_USER_SPLITS, VOICE_AUTO_SPLIT, "enroll", "genuine")
        },
        "templates": templates,
        "stage2": stage2,
        "face_user_ok": face_user_ok,
        "voice_user_ok": voice_user_ok,
        "ready_to_train": ready_to_train,
        "hints": _hints(face, voice, templates),
    }


def _hints(face: dict, voice: dict, templates: dict) -> list[str]:
    hints: list[str] = []
    if not templates["face"] or not templates["voice"]:
        hints.append("Enroll this driver first on /register (templates required).")
    if face["enroll"] + face["genuine"] < MIN_PER_USER_BOX:
        hints.append("Need enroll (or genuine) face samples as bonafide positives.")
    if voice["enroll"] + voice["genuine"] < MIN_PER_USER_BOX:
        hints.append("Need enroll (or genuine) voice clips as bonafide positives.")
    for s in FACE_USER_SPLITS:
        if face[s] < MIN_PER_USER_BOX:
            hints.append(f"Capture ≥{MIN_PER_USER_BOX} face/{s} samples.")
    for s in VOICE_USER_SPLITS:
        if voice[s] < MIN_PER_USER_BOX:
            hints.append(f"Capture ≥{MIN_PER_USER_BOX} voice/{s} samples.")
    if face[FACE_AUTO_SPLIT] < MIN_AUTO_SAMPLES:
        hints.append("Blur attacks are auto-generated on Train (from enroll faces).")
    if voice[VOICE_AUTO_SPLIT] < MIN_AUTO_SAMPLES:
        hints.append("Silent attacks are auto-generated on Train.")
    return hints


def sync_genuine_from_enroll(data_root: str | Path, driver_id: str) -> dict:
    """Copy enroll → genuine when genuine is empty (calibrators need positives)."""
    root = ensure_driver_layout(data_root, driver_id)
    copied = {"face": 0, "voice": 0}

    face_gen = root / "face" / "genuine"
    if _count_images(face_gen) == 0:
        for src in list_enroll_images(root):
            dst = face_gen / src.name.replace("enroll_", "genuine_", 1)
            if not dst.exists():
                shutil.copy2(src, dst)
                copied["face"] += 1

    voice_gen = root / "voice" / "genuine"
    if _count_wavs(voice_gen) == 0:
        for src in list_enroll_wavs(root):
            dst = voice_gen / src.name.replace("enroll_", "genuine_", 1)
            if not dst.exists():
                shutil.copy2(src, dst)
                copied["voice"] += 1

    return copied


def auto_generate_face_blur(
    data_root: str | Path,
    driver_id: str,
    *,
    n: int = 5,
    blur_ksize: int = 31,
) -> list[Path]:
    """Synthesize attack_blur JPGs from enroll/genuine faces."""
    import cv2  # type: ignore

    root = ensure_driver_layout(data_root, driver_id)
    sources = list_enroll_images(root) + sorted(
        (root / "face" / "genuine").glob("*.jpg")
    )
    if not sources:
        raise ValueError("no enroll/genuine faces to blur — capture enroll faces first")

    out_dir = root / "face" / FACE_AUTO_SPLIT
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear previous auto blur so Train is deterministic
    for old in out_dir.glob("auto_blur_*.jpg"):
        old.unlink(missing_ok=True)

    written: list[Path] = []
    k = blur_ksize if blur_ksize % 2 == 1 else blur_ksize + 1
    for i, src in enumerate(sources[: max(n, MIN_AUTO_SAMPLES)]):
        bgr = cv2.imread(str(src))
        if bgr is None:
            continue
        blurred = cv2.GaussianBlur(bgr, (k, k), 0)
        # Extra soft blur pass for PAD separability
        blurred = cv2.GaussianBlur(blurred, (k, k), 0)
        idx = next_enroll_index(out_dir, "auto_blur", "jpg")
        path = out_dir / f"auto_blur_{idx:02d}.jpg"
        cv2.imwrite(str(path), blurred)
        written.append(path)
    if len(written) < MIN_AUTO_SAMPLES:
        raise ValueError(
            f"could only write {len(written)} blur samples (need ≥{MIN_AUTO_SAMPLES})"
        )
    return written


def auto_generate_voice_silent(
    data_root: str | Path,
    driver_id: str,
    *,
    n: int = 5,
    seconds: float = 2.0,
    sr: int = 16_000,
) -> list[Path]:
    """Write near-silent WAVs into attack_silent."""
    root = ensure_driver_layout(data_root, driver_id)
    out_dir = root / "voice" / VOICE_AUTO_SPLIT
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("auto_silent_*.wav"):
        old.unlink(missing_ok=True)

    written: list[Path] = []
    n_samples = int(sr * seconds)
    rng = np.random.default_rng(0)
    for i in range(max(n, MIN_AUTO_SAMPLES)):
        # Tiny noise floor — not pure zeros (ECAPA / quality path)
        audio = (rng.normal(0.0, 1e-4, n_samples)).astype(np.float32)
        pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        idx = next_enroll_index(out_dir, "auto_silent", "wav")
        path = out_dir / f"auto_silent_{idx:02d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        written.append(path)
    return written


def prepare_improved_auth_datasets(data_root: str | Path, driver_id: str) -> dict:
    """Auto-fill blur + silent and sync genuine from enroll before training."""
    genuine = sync_genuine_from_enroll(data_root, driver_id)
    blur = auto_generate_face_blur(data_root, driver_id)
    silent = auto_generate_voice_silent(data_root, driver_id)
    return {
        "genuine_copied": genuine,
        "blur_paths": [p.name for p in blur],
        "silent_paths": [p.name for p in silent],
    }
