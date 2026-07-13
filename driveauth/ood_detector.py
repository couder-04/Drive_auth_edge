"""Out-of-distribution detection per modality (§8a.6).

Missing baselines fail CLOSED: a scored modality without a baseline is treated
as OOD-unavailable so confidence drops and policy prefers STEP_UP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from driveauth import config

logger = logging.getLogger("driveauth.ood")

_OOD_Z_THRESH = config.OOD_Z_THRESH
_OOD_COSINE_THRESH = config.OOD_COSINE_THRESH


@dataclass
class OODEvaluation:
    flags: dict[str, bool] = field(default_factory=dict)
    baseline_missing: dict[str, bool] = field(default_factory=dict)
    unavailable: bool = (
        False  # detector itself broken / no stats at all for scored mods
    )


class _ModalityOOD:
    def __init__(self, mean: np.ndarray | None, std: np.ndarray | None):
        self._mean = mean
        self._std = std

    @property
    def has_baseline(self) -> bool:
        return self._mean is not None

    @classmethod
    def from_store(cls, stats_path: Path) -> _ModalityOOD:
        mean = std = None
        if stats_path.exists():
            try:
                data = np.load(stats_path)
                mean = data["mean"].astype(np.float32)
                std = data["std"].astype(np.float32)
                std = np.where(std < 1e-6, 1e-6, std)
            except Exception as exc:
                logger.warning("OOD: stats load failed (%s)", exc)
        return cls(mean, std)

    def is_ood(self, embedding: np.ndarray | None) -> tuple[bool, float, bool]:
        """
        Returns (is_ood, distance, baseline_missing).

        If there is no baseline and an embedding was provided, baseline_missing
        is True and is_ood is True (fail closed).
        """
        if embedding is None:
            return False, 0.0, False
        if self._mean is None:
            return True, 0.0, True
        emb = embedding.astype(np.float32).ravel()
        if emb.shape != self._mean.shape:
            logger.warning("OOD: shape mismatch %s vs %s", emb.shape, self._mean.shape)
            return True, 0.0, True
        if self._std is not None:
            z = np.abs(emb - self._mean) / self._std
            dist = float(np.sqrt(np.mean(z**2)))
            return dist > _OOD_Z_THRESH, dist, False
        a = emb / (np.linalg.norm(emb) + 1e-8)
        b = self._mean / (np.linalg.norm(self._mean) + 1e-8)
        cos_dist = float(1.0 - np.dot(a, b))
        return cos_dist > _OOD_COSINE_THRESH, cos_dist, False


class OODDetector:
    def __init__(self, voice: _ModalityOOD, face: _ModalityOOD, finger: _ModalityOOD):
        self.voice = voice
        self.face = face
        self.finger = finger

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> OODDetector:
        store = Path(store_dir) / "ood_stats"
        return cls(
            voice=_ModalityOOD.from_store(store / f"voice_{driver_id}.npz"),
            face=_ModalityOOD.from_store(store / f"face_{driver_id}.npz"),
            finger=_ModalityOOD.from_store(store / f"finger_{driver_id}.npz"),
        )

    @classmethod
    def seed_baselines(
        cls,
        store_dir: str,
        driver_id: str = "driver1",
        *,
        voice_dim: int = 192,
        face_dim: int = 512,
        finger_dim: int = 64,
    ) -> OODDetector:
        """Write neutral baselines (mean=0, std=1) for demos/tests."""
        store = Path(store_dir) / "ood_stats"
        store.mkdir(parents=True, exist_ok=True)
        for name, dim in (
            ("voice", voice_dim),
            ("face", face_dim),
            ("finger", finger_dim),
        ):
            path = store / f"{name}_{driver_id}.npz"
            np.savez(
                path,
                mean=np.zeros(dim, dtype=np.float32),
                std=np.ones(dim, dtype=np.float32),
            )
        return cls.load(store_dir, driver_id)

    def evaluate(
        self,
        *,
        voice_emb: np.ndarray | None = None,
        face_emb: np.ndarray | None = None,
        finger_emb: np.ndarray | None = None,
    ) -> OODEvaluation:
        out = OODEvaluation()
        for name, mod, emb in (
            ("voice", self.voice, voice_emb),
            ("face", self.face, face_emb),
            ("finger", self.finger, finger_emb),
        ):
            if emb is None:
                out.flags[name] = False
                out.baseline_missing[name] = False
                continue
            is_ood, _, missing = mod.is_ood(emb)
            out.flags[name] = is_ood
            out.baseline_missing[name] = missing
            if missing:
                out.unavailable = True
        return out
