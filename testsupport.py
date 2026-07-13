"""Shared test helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from driveauth import DriveAuth
from driveauth.ood_detector import OODDetector


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
    store = tempfile.mkdtemp(prefix="driveauth_test_")
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
