"""Passive behavioral monitor — feeds Risk, never Trust."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

from driveauth.types import ModalityResult

logger = logging.getLogger("driveauth.matchers.behavioral")


class BehavioralMonitor:
    def __init__(self, session, driver_profile: np.ndarray | None, window: int = 50):
        self._session = session
        self._profile = driver_profile
        self._window = window
        self._buf: list[np.ndarray] = []
        self._score: float | None = None
        self._lock = threading.Lock()

    @classmethod
    def load(cls, store_dir: str, driver_id: str = "driver1") -> BehavioralMonitor:
        store = Path(store_dir)
        session = None
        driver_profile: np.ndarray | None = None

        onnx_path = store / "behavioral_lstm_int8.onnx"
        if onnx_path.exists():
            try:
                import onnxruntime as ort  # type: ignore

                session = ort.InferenceSession(
                    str(onnx_path),
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                logger.info("BehavioralMonitor: LSTM loaded")
            except Exception as exc:
                logger.warning("BehavioralMonitor: ONNX load failed (%s)", exc)

        profile_enc = store / "behavioral" / f"{driver_id}.enc"
        if profile_enc.exists():
            try:
                from cryptography.fernet import Fernet  # type: ignore

                key_path = store / ".bio_key"
                if key_path.exists():
                    f = Fernet(key_path.read_bytes())
                    raw = f.decrypt(profile_enc.read_bytes())
                    driver_profile = np.frombuffer(raw, dtype=np.float32).copy()
                    logger.info("BehavioralMonitor: profile loaded for %s", driver_id)
            except Exception as exc:
                logger.error("BehavioralMonitor: profile load failed: %s", exc)

        return cls(session, driver_profile)

    def update(self, sensor: dict[str, float]) -> None:
        vec = np.array(
            [
                sensor.get("steering_torque_nm", 0.0),
                sensor.get("brake_pressure_bar", 0.0),
                sensor.get("throttle_pct", 0.0),
                sensor.get("seat_pressure_kpa", 0.0),
                sensor.get("lateral_accel_g", 0.0),
                sensor.get("yaw_rate_dps", 0.0),
                sensor.get("vehicle_speed_kmh", 0.0),
            ],
            dtype=np.float32,
        )
        with self._lock:
            self._buf.append(vec)
            if len(self._buf) > self._window:
                self._buf.pop(0)
            self._score = self._compute_score()

    def _compute_score(self) -> float | None:
        if self._session is None or self._profile is None or len(self._buf) < 5:
            return None
        try:
            seq = np.stack(self._buf[-self._window :], axis=0)[np.newaxis]
            input_name = self._session.get_inputs()[0].name
            out = self._session.run(None, {input_name: seq})[0][0]
            norm_out = out / (np.linalg.norm(out) + 1e-8)
            norm_profile = self._profile / (np.linalg.norm(self._profile) + 1e-8)
            return float(np.clip(float(np.dot(norm_out, norm_profile)), 0.0, 1.0))
        except Exception:
            return None

    @property
    def available(self) -> bool:
        return self._session is not None and self._profile is not None

    def get_score(self) -> ModalityResult:
        with self._lock:
            s = self._score
            avail = self.available
        if not avail or s is None:
            return ModalityResult(score=None, confident=False, available=False)
        confident = len(self._buf) >= 10
        return ModalityResult(score=s, confident=confident, available=True)
