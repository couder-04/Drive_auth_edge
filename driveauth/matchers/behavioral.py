"""Passive behavioral monitor — feeds Risk, never Trust."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from driveauth.template_store import load_embedding
from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.matchers.behavioral")

# Canonical live + CSV feature order (portable OBD-II / IMU / steering bus).
BEHAVIORAL_FEATURE_KEYS: tuple[str, ...] = (
    "steering_angle_deg",
    "steering_rate_dps",
    "throttle_pct",
    "brake_pedal_pct",
    "longitudinal_accel_g",
    "lateral_accel_g",
    "yaw_rate_dps",
    "vehicle_speed_kmh",
)

# Aggregates used by windowed GBM (mean/std/min/max/last × 8 features).
_STAT_NAMES = ("mean", "std", "min", "max", "last")
WINDOW_STAT_KEYS: tuple[str, ...] = tuple(
    f"{stat}_{key}" for stat in _STAT_NAMES for key in BEHAVIORAL_FEATURE_KEYS
)


def window_stat_features(seq: np.ndarray) -> np.ndarray:
    """Flatten a (T, F) window into GBM-friendly stats (len = 5 * F)."""
    seq = np.asarray(seq, dtype=np.float32)
    if seq.ndim != 2 or seq.shape[1] != len(BEHAVIORAL_FEATURE_KEYS):
        raise ValueError(f"expected (T, {len(BEHAVIORAL_FEATURE_KEYS)}), got {seq.shape}")
    parts = [
        seq.mean(axis=0),
        seq.std(axis=0),
        seq.min(axis=0),
        seq.max(axis=0),
        seq[-1],
    ]
    return np.concatenate(parts).astype(np.float32)


class BehavioralMonitor:
    def __init__(
        self,
        session,
        driver_profile: np.ndarray | None,
        *,
        window: int = 50,
        score_mode: str = "cosine",
        arch: str = "lstm",
    ):
        self._session = session
        self._profile = driver_profile
        self._window = window
        self._score_mode = score_mode  # "cosine" | "proba"
        self._arch = arch
        self._buf: list[np.ndarray] = []
        self._score: float | None = None
        self._lock = threading.Lock()

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> BehavioralMonitor:
        store = Path(store_dir)
        session = None
        score_mode = "cosine"
        arch = "lstm"
        window = 50

        meta_path = store / "behavioral_bakeoff.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                score_mode = str(meta.get("score_mode", score_mode))
                arch = str(meta.get("arch", arch))
                window = int(meta.get("window", window))
            except Exception as exc:
                logger.warning("BehavioralMonitor: meta read failed (%s)", exc)

        onnx_path = store / "behavioral_model.onnx"
        if not onnx_path.exists():
            onnx_path = store / "behavioral_lstm_int8.onnx"
        if onnx_path.exists():
            try:
                import onnxruntime as ort  # type: ignore

                session = ort.InferenceSession(
                    str(onnx_path),
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                logger.info("BehavioralMonitor: %s model loaded (%s)", arch, onnx_path.name)
            except Exception as exc:
                logger.warning("BehavioralMonitor: ONNX load failed (%s)", exc)

        driver_profile = load_embedding(store, f"behavioral/{driver_id}.enc")
        if driver_profile is not None:
            logger.info("BehavioralMonitor: profile loaded for %s", driver_id)

        return cls(
            session,
            driver_profile,
            window=window,
            score_mode=score_mode,
            arch=arch,
        )

    def update(self, sensor: dict[str, float]) -> None:
        vec = np.array(
            [float(sensor.get(k, 0.0)) for k in BEHAVIORAL_FEATURE_KEYS],
            dtype=np.float32,
        )
        with self._lock:
            self._buf.append(vec)
            if len(self._buf) > self._window:
                self._buf.pop(0)
            self._score = self._compute_score()

    def _compute_score(self) -> float | None:
        if self._session is None or len(self._buf) < 5:
            return None
        if self._score_mode == "cosine" and self._profile is None:
            return None
        try:
            seq = np.stack(self._buf[-self._window :], axis=0)
            if self._score_mode == "proba":
                feats = window_stat_features(seq)[np.newaxis]
                input_name = self._session.get_inputs()[0].name
                out = self._session.run(None, {input_name: feats})
                return _proba_from_onnx(out)

            # cosine embedding path (LSTM / GRU)
            batched = seq[np.newaxis].astype(np.float32)
            input_name = self._session.get_inputs()[0].name
            out = self._session.run(None, {input_name: batched})[0][0]
            norm_out = out / (np.linalg.norm(out) + 1e-8)
            norm_profile = self._profile / (np.linalg.norm(self._profile) + 1e-8)
            sim = float(np.dot(norm_out, norm_profile))
            # embeddings are L2-normalized; map cosine [-1,1] → [0,1]
            return float(np.clip((sim + 1.0) * 0.5, 0.0, 1.0))
        except Exception as exc:
            logger.debug("BehavioralMonitor score failed: %s", exc)
            return None

    @property
    def available(self) -> bool:
        if self._session is None:
            return False
        if self._score_mode == "proba":
            return True
        return self._profile is not None

    def get_score(self) -> ModalityResult:
        with self._lock:
            s = self._score
            avail = self.available
        if not avail or s is None:
            return ModalityResult(score=None, confident=False, available=False)
        confident = len(self._buf) >= 10
        return ModalityResult(score=s, confident=confident, available=True)


def _proba_from_onnx(outputs: list) -> float:
    """Map classifier ONNX outputs → P(genuine) in [0, 1]."""
    if not outputs:
        return 0.0
    # Prefer probability tensor (often outputs[1] when [label, proba])
    for out in reversed(outputs):
        arr = np.asarray(out, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            return float(np.clip(arr[0, -1], 0.0, 1.0))
        flat = arr.reshape(-1)
        if flat.size >= 2 and flat.max() <= 1.0 + 1e-6 and flat.min() >= -1e-6:
            return float(np.clip(flat[-1], 0.0, 1.0))
        if flat.size == 1 and 0.0 <= flat[0] <= 1.0:
            return float(flat[0])
    arr = np.asarray(outputs[0]).reshape(-1)
    return float(np.clip(arr[-1] if arr.size else 0.0, 0.0, 1.0))

