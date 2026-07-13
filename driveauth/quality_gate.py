"""Pre-matching quality assessment (§8a.5).

Every biometric MUST pass these gates before a matcher runs. Bad captures are
skipped (confident=False) so garbage scores never enter fusion.
"""

from __future__ import annotations

import logging

import numpy as np

from driveauth import config
from driveauth.types import QualityFlags

logger = logging.getLogger("driveauth.quality")

_VOICE_MIN_SNR_DB = config.Q_VOICE_MIN_SNR
_VOICE_CLIP_FRAC = config.Q_VOICE_CLIP_FRAC
_VOICE_MIN_SECONDS = config.Q_VOICE_MIN_SEC
_FACE_MIN_SHARPNESS = config.Q_FACE_MIN_SHARP
_FACE_MIN_BRIGHT = config.Q_FACE_MIN_BRIGHT
_FACE_MAX_BRIGHT = config.Q_FACE_MAX_BRIGHT
_FACE_MIN_FRAC = config.FACE_MIN_FRAC
_FINGER_MIN_CONTACT = config.Q_FINGER_MIN_CONTACT


def _snr_db(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    frame = 400
    n = (audio.size // frame) * frame
    if n < frame:
        return 0.0
    energies = (audio[:n].reshape(-1, frame) ** 2).mean(axis=1)
    energies = np.sqrt(energies + 1e-12)
    noise = np.percentile(energies, 10)
    speech = np.percentile(energies, 90)
    if noise <= 1e-9:
        return 40.0
    return float(20.0 * np.log10(max(speech / noise, 1e-6)))


def score_voice(
    audio_f32: np.ndarray, sample_rate: int = 16_000
) -> tuple[bool, float, list[str]]:
    notes: list[str] = []
    if audio_f32 is None or audio_f32.size == 0:
        return False, 0.0, ["voice_no_audio"]

    duration = audio_f32.size / sample_rate
    if duration < _VOICE_MIN_SECONDS:
        notes.append("voice_too_short")

    clip_frac = float(np.mean(np.abs(audio_f32) > 0.995))
    if clip_frac > _VOICE_CLIP_FRAC:
        notes.append("voice_clipping")

    snr = _snr_db(audio_f32)
    if snr < _VOICE_MIN_SNR_DB:
        notes.append("voice_low_snr")

    q_snr = float(np.clip((snr - _VOICE_MIN_SNR_DB) / 24.0 + 0.5, 0.0, 1.0))
    q_clip = float(np.clip(1.0 - clip_frac / max(_VOICE_CLIP_FRAC, 1e-6), 0.0, 1.0))
    quality = 0.6 * q_snr + 0.4 * q_clip
    ok = (
        (duration >= _VOICE_MIN_SECONDS)
        and (clip_frac <= _VOICE_CLIP_FRAC)
        and (snr >= _VOICE_MIN_SNR_DB)
    )
    return ok, quality, notes


def score_face(
    frame_gray: np.ndarray | None,
    *,
    face_frac: float | None = None,
    frontal_ok: bool | None = None,
) -> tuple[bool, float, list[str]]:
    """Blur / brightness / size / frontal-pose gate before face matching."""
    notes: list[str] = []
    if frame_gray is None or getattr(frame_gray, "size", 0) == 0:
        return False, 0.0, ["face_no_frame"]

    f = frame_gray.astype(np.float32)
    if f.ndim == 3:
        f = f.mean(axis=2)
    lap = (
        -4.0 * f
        + np.roll(f, 1, 0)
        + np.roll(f, -1, 0)
        + np.roll(f, 1, 1)
        + np.roll(f, -1, 1)
    )
    sharpness = float(lap.var())
    brightness = float(f.mean())

    if sharpness < _FACE_MIN_SHARPNESS:
        notes.append("face_blurry_or_occluded")
    if brightness < _FACE_MIN_BRIGHT:
        notes.append("face_underexposed")
    if brightness > _FACE_MAX_BRIGHT:
        notes.append("face_overexposed")
    if face_frac is not None and face_frac < _FACE_MIN_FRAC:
        notes.append("face_too_small")
    if frontal_ok is False:
        notes.append("face_not_frontal")

    q_sharp = float(np.clip(sharpness / (_FACE_MIN_SHARPNESS * 4.0), 0.0, 1.0))
    q_bright = float(np.clip(1.0 - abs(brightness - 130.0) / 130.0, 0.0, 1.0))
    quality = 0.65 * q_sharp + 0.35 * q_bright
    ok = (
        sharpness >= _FACE_MIN_SHARPNESS
        and _FACE_MIN_BRIGHT <= brightness <= _FACE_MAX_BRIGHT
        and (face_frac is None or face_frac >= _FACE_MIN_FRAC)
        and (frontal_ok is not False)
    )
    return ok, quality, notes


def score_finger(
    contact_fraction: float | None,
    ridge_clarity: float | None = None,
    pressure: float | None = None,
) -> tuple[bool, float, list[str]]:
    notes: list[str] = []
    if contact_fraction is None:
        return False, 0.0, ["finger_no_metric"]
    if contact_fraction < _FINGER_MIN_CONTACT:
        notes.append("finger_low_contact")
    if pressure is not None and pressure < 0.25:
        notes.append("finger_low_pressure")
    clarity = 1.0 if ridge_clarity is None else float(np.clip(ridge_clarity, 0.0, 1.0))
    press_q = 1.0 if pressure is None else float(np.clip(pressure, 0.0, 1.0))
    quality = float(
        np.clip(
            0.4 * contact_fraction / max(_FINGER_MIN_CONTACT, 1e-6)
            + 0.35 * clarity
            + 0.25 * press_q,
            0.0,
            1.0,
        )
    )
    ok = contact_fraction >= _FINGER_MIN_CONTACT and (
        pressure is None or pressure >= 0.25
    )
    return ok, quality, notes


class QualityGate:
    def evaluate(
        self,
        *,
        voice_audio: np.ndarray | None = None,
        face_frame_gray: np.ndarray | None = None,
        face_frac: float | None = None,
        face_frontal_ok: bool | None = None,
        finger_contact: float | None = None,
        finger_clarity: float | None = None,
        finger_pressure: float | None = None,
        hardware_fault: bool = False,
    ) -> QualityFlags:
        flags = QualityFlags(hardware_fault=hardware_fault)

        if voice_audio is not None:
            ok, q, notes = score_voice(voice_audio)
            flags.voice_ok, flags.voice_q = ok, q
            flags.notes.extend(notes)

        if face_frame_gray is not None:
            ok, q, notes = score_face(
                face_frame_gray, face_frac=face_frac, frontal_ok=face_frontal_ok
            )
            flags.face_ok, flags.face_q = ok, q
            flags.notes.extend(notes)

        if finger_contact is not None:
            ok, q, notes = score_finger(finger_contact, finger_clarity, finger_pressure)
            flags.finger_ok, flags.finger_q = ok, q
            flags.notes.extend(notes)

        return flags
