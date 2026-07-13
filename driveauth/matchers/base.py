"""Biometric matcher protocol and registry."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from driveauth.types import ModalityResult


class VoiceMatcher(Protocol):
    def score(
        self, audio_f32: np.ndarray, sample_rate: int = 16_000
    ) -> ModalityResult: ...


class FaceMatcher(Protocol):
    def capture_and_score(self) -> ModalityResult: ...


class FingerMatcher(Protocol):
    def capture_and_score(self) -> ModalityResult: ...


class BehavioralMonitor(Protocol):
    def update(self, sensor: dict[str, float]) -> None: ...
    def get_score(self) -> ModalityResult: ...
