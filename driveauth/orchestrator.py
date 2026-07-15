"""Optional dynamic trust-weight orchestrator (PolicyMLP ONNX)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from driveauth import config

logger = logging.getLogger("driveauth.orchestrator")

_BASE_W = {
    "voice": config.TRUST_W_VOICE,
    "face": config.TRUST_W_FACE,
    "finger": config.TRUST_W_FINGER,
}
_UNCERTAINTY_THRESH = config.ORCH_UNCERTAINTY


@dataclass
class OrchestratorContext:
    ambient_noise_rms: float = 0.02
    snr_db: float = 20.0
    vehicle_speed_kmh: float = 0.0
    time_hour: float = 12.0
    voice_signal_conf: float = 1.0
    face_camera_quality: float = 1.0
    finger_sensor_quality: float = 1.0
    behavioral_data_secs: float = 0.0
    auth_streak_successes: int = 0
    auth_streak_failures: int = 0
    last_deny_secs_ago: float = 9999.0
    transaction_tier: int = 0
    is_highway: bool = False
    is_parked: bool = False
    is_tunnel: bool = False
    voice_raw_score: float = 0.5
    face_raw_score: float = 0.5
    finger_raw_score: float = 0.5
    behavioral_raw_score: float = 0.5

    def to_vector(self) -> np.ndarray:
        hour_rad = self.time_hour * 2 * math.pi / 24.0
        return np.array(
            [
                self.ambient_noise_rms,
                self.snr_db / 40.0,
                self.vehicle_speed_kmh / 200.0,
                math.sin(hour_rad),
                math.cos(hour_rad),
                self.voice_signal_conf,
                self.face_camera_quality,
                self.finger_sensor_quality,
                min(self.behavioral_data_secs / 30.0, 1.0),
                min(self.auth_streak_successes / 5.0, 1.0),
                min(self.auth_streak_failures / 3.0, 1.0),
                float(self.transaction_tier) / 2.0,
                float(self.is_highway),
                float(self.is_parked),
                float(self.is_tunnel),
                self.voice_raw_score,
                self.face_raw_score,
                self.finger_raw_score,
                self.behavioral_raw_score,
                min(self.last_deny_secs_ago / 300.0, 1.0),
            ],
            dtype=np.float32,
        )


class PolicyMLP:
    def __init__(self, session):
        self._session = session
        self._input_name = session.get_inputs()[0].name

    @classmethod
    def load(cls, model_path: str) -> PolicyMLP | None:
        try:
            import onnxruntime as ort  # type: ignore

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            session = ort.InferenceSession(
                model_path, sess_options=opts, providers=["CPUExecutionProvider"]
            )
            return cls(session)
        except Exception as exc:
            logger.warning("PolicyMLP: load failed (%s)", exc)
            return None

    def infer(self, ctx: OrchestratorContext) -> tuple[dict[str, float], float, float]:
        vec = ctx.to_vector()[np.newaxis]
        out = self._session.run(None, {self._input_name: vec})[0][0]
        w_raw = out[:3]
        w_exp = np.exp(w_raw - w_raw.max())
        w_norm = w_exp / w_exp.sum()
        weights = {
            "voice": float(w_norm[0]),
            "face": float(w_norm[1]),
            "finger": float(w_norm[2]),
        }
        uncertainty = float(1.0 / (1.0 + math.exp(-out[4])))
        thresh_delta = float(math.tanh(out[5]) * 0.15)
        return weights, uncertainty, thresh_delta


class DynamicOrchestrator:
    def __init__(self, mlp: PolicyMLP | None):
        self._mlp = mlp

    @classmethod
    def load(cls, store_dir: str) -> DynamicOrchestrator:
        mlp_path = Path(store_dir) / "orchestrator_mlp.onnx"
        mlp = PolicyMLP.load(str(mlp_path)) if mlp_path.exists() else None
        if mlp is None:
            logger.info("DynamicOrchestrator: no MLP — static trust weights")
        return cls(mlp)

    def get_weights(self, ctx: OrchestratorContext) -> tuple[dict[str, float], float]:
        if self._mlp is None:
            return dict(_BASE_W), 0.0
        weights, uncertainty, thresh_delta = self._mlp.infer(ctx)
        if uncertainty > _UNCERTAINTY_THRESH:
            logger.info(
                "Orchestrator: high uncertainty %.3f — static fallback", uncertainty
            )
            return dict(_BASE_W), thresh_delta
        return weights, thresh_delta
