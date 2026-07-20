"""Mic array capture — 16 kHz mono float32 for ``driveauth.matchers.voice``."""

from __future__ import annotations

from hardware.ir_capture import (
    AudioBackend,
    MicArrayCapture,
    NumpyAudioBackend,
    VOICE_SAMPLE_RATE,
)

__all__ = [
    "AudioBackend",
    "MicArrayCapture",
    "NumpyAudioBackend",
    "VOICE_SAMPLE_RATE",
]
