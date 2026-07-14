"""Decode uploaded WAV / PCM for live auth (16 kHz mono float32)."""

from __future__ import annotations

import io
import wave

import numpy as np


def wav_bytes_to_float32(data: bytes, *, target_sr: int = 16_000) -> np.ndarray:
    """Load PCM WAV bytes → mono float32 in [-1, 1], resampled if needed."""
    if not data:
        raise ValueError("empty audio")
    with wave.open(io.BytesIO(data), "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sw == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width: {sw}")

    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)

    if sr != target_sr and len(audio) > 0:
        # Linear resample — good enough for demo STT→ECAPA path.
        duration = len(audio) / float(sr)
        n_out = max(1, int(round(duration * target_sr)))
        x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        audio = np.interp(x_new, x_old, audio).astype(np.float32)
    else:
        audio = audio.astype(np.float32)

    return audio
