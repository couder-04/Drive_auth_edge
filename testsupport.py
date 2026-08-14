"""Shared test helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from driveauth import DriveAuth
from driveauth.ood_detector import OODDetector
from driveauth.types import ModalityResult


class HardwareFingerStandIn:
    """Finger matcher that is not ``MockFingerMatcher``.

    Tests that still need the "Accept via real stage-3" path inject this and
    set ``fingerprint_available=True``. ``isinstance(..., MockFingerMatcher)``
    must stay false so forced stage-3 rigor cannot be satisfied by a mock.
    """

    def __init__(self, score: float = 0.85):
        self._score = score
        self.contact = 0.8
        self.pressure = 0.7
        self.clarity = 0.9

    def capture_metrics(self):
        return self.contact, self.clarity, self.pressure

    def score_scan(self):
        return ModalityResult(
            self._score, True, embedding=np.zeros(64, dtype=np.float32)
        )

    def capture_and_score(self):
        return self.score_scan()


def good_audio(seconds: float = 1.5, sr: int = 16_000) -> np.ndarray:
    n = int(sr * seconds)
    t = np.linspace(0, seconds, n, dtype=np.float32)
    rng = np.random.default_rng(0)
    envelope = 0.05 + 0.15 * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))
    speech = envelope * np.sin(2 * np.pi * 180 * t)
    noise = 0.005 * rng.standard_normal(n).astype(np.float32)
    return (speech + noise).astype(np.float32)


def mature(auth: DriveAuth) -> None:
    auth._profile.seed_mature()


def make_auth(**kwargs) -> DriveAuth:
    store = kwargs.pop("store_dir", None) or tempfile.mkdtemp(prefix="driveauth_test_")
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True, **kwargs)
    return auth


def write_beneficiaries(auth: DriveAuth, names: list[str]) -> None:
    path = Path(auth._store) / "beneficiaries" / f"{auth.driver_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(names) + "\n")


def clear_ood(auth: DriveAuth) -> None:
    """Remove OOD baselines so the detector fails closed."""
    store = Path(auth._store) / "ood_stats"
    if store.exists():
        for p in store.glob("*.npz"):
            p.unlink()
    auth._engine._ood = OODDetector.load(auth._store, auth.driver_id)


def seed_ood(auth: DriveAuth) -> None:
    auth._engine._ood = OODDetector.seed_baselines(auth._store, auth.driver_id)
