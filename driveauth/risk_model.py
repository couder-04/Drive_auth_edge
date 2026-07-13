"""Adaptive risk model — GPS/CAN/behaviour/transaction context (§7)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth.types import RiskContext, clip01

logger = logging.getLogger("driveauth.risk")

RISK_APPROVE = config.RISK_APPROVE
RISK_REJECT = config.RISK_REJECT


class RiskModel:
    _FEATURE_ORDER = (
        "amount_z",
        "amount_norm",
        "beneficiary_novel",
        "dist_from_home",
        "out_of_zone",
        "night",
        "moving_fast",
        "ignition_off_anomaly",
        "tunnel",
        "behavior_anomaly",
    )

    def __init__(self, session=None):
        self._session = session
        self._input_name = session.get_inputs()[0].name if session is not None else None

    @classmethod
    def load(cls, store_dir: str) -> RiskModel:
        path = Path(store_dir) / "risk_gbt.onnx"
        session = None
        if path.exists():
            try:
                import onnxruntime as ort  # type: ignore

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                session = ort.InferenceSession(
                    str(path), sess_options=opts, providers=["CPUExecutionProvider"]
                )
                logger.info("RiskModel: trained model loaded (CPU)")
            except Exception as exc:
                logger.warning("RiskModel: load failed (%s) — additive fallback", exc)
        else:
            logger.info("RiskModel: no trained model — using additive fallback")
        return cls(session)

    def _features(self, ctx: RiskContext) -> dict[str, float]:
        amount_z = 0.0
        if ctx.amount_std > 1e-6:
            amount_z = (ctx.amount - ctx.amount_mean) / ctx.amount_std
        amount_z = float(np.clip(amount_z, -3.0, 6.0))

        night = 1.0 if (ctx.time_hour < 5.0 or ctx.time_hour >= 23.0) else 0.0
        moving_fast = clip01((ctx.speed_kmh - 20.0) / 80.0)
        ign_anom = 0.0 if ctx.ignition_on else 1.0
        behavior_anom = 0.0
        if ctx.behavioral_score is not None:
            behavior_anom = clip01(1.0 - ctx.behavioral_score)

        return {
            "amount_z": amount_z,
            "amount_norm": clip01(ctx.amount / 100_000.0),
            "beneficiary_novel": 0.0 if ctx.beneficiary_known else 1.0,
            "dist_from_home": clip01(ctx.dist_from_home_km / 50.0),
            "out_of_zone": 0.0 if ctx.in_trusted_zone else 1.0,
            "night": night,
            "moving_fast": moving_fast,
            "ignition_off_anomaly": ign_anom,
            "tunnel": 1.0 if ctx.is_tunnel else 0.0,
            "behavior_anomaly": behavior_anom,
        }

    def _vector(self, feats: dict[str, float]) -> np.ndarray:
        return np.array([[feats[k] for k in self._FEATURE_ORDER]], dtype=np.float32)

    @staticmethod
    def _risk_from_onnx_outputs(outputs: list) -> float:
        """Map GBT ONNX outputs → risk in [0, 1].

        Handles: scalar score, [p0, p1] probabilities, or (label, probs) pairs.
        Prefers P(suspicious)=class 1 when a 2-column probability is present.
        """
        if not outputs:
            return 0.0
        # (label, probability) style from LightGBM / sklearn converters
        if len(outputs) >= 2:
            prob = np.asarray(outputs[1])
            if prob.ndim == 2 and prob.shape[-1] >= 2:
                return clip01(float(prob.reshape(-1, prob.shape[-1])[0, 1]))
            flat = np.ravel(prob)
            if flat.size:
                return clip01(float(flat[-1]))
        arr = np.asarray(outputs[0])
        if arr.ndim == 2 and arr.shape[-1] >= 2:
            return clip01(float(arr[0, 1]))
        return clip01(float(np.ravel(arr)[0]))

    def score(self, ctx: RiskContext) -> tuple[float, list[str]]:
        feats = self._features(ctx)

        if self._session is not None:
            try:
                out = self._session.run(None, {self._input_name: self._vector(feats)})
                risk = self._risk_from_onnx_outputs(out)
                return risk, self._reasons(feats)
            except Exception as exc:
                logger.warning("RiskModel: inference failed (%s)", exc)

        risk = (
            0.22 * clip01(feats["amount_z"] / 4.0)
            + 0.14 * feats["amount_norm"]
            + 0.16 * feats["beneficiary_novel"]
            + 0.12 * feats["dist_from_home"]
            + 0.12 * feats["out_of_zone"]
            + 0.06 * feats["night"]
            + 0.06 * feats["moving_fast"]
            + 0.04 * feats["ignition_off_anomaly"]
            + 0.02 * feats["tunnel"]
            + 0.06 * feats["behavior_anomaly"]
        )
        return clip01(risk), self._reasons(feats)

    @staticmethod
    def _reasons(feats: dict[str, float]) -> list[str]:
        reasons: list[str] = []
        if feats["amount_z"] > 2.0:
            reasons.append("amount_far_above_usual")
        if feats["amount_norm"] > 0.5:
            reasons.append("large_absolute_amount")
        if feats["beneficiary_novel"] > 0.5:
            reasons.append("first_time_beneficiary")
        if feats["out_of_zone"] > 0.5:
            reasons.append("unfamiliar_location")
        if feats["dist_from_home"] > 0.6:
            reasons.append("far_from_home")
        if feats["night"] > 0.5:
            reasons.append("unusual_hour")
        if feats["moving_fast"] > 0.3:
            reasons.append("transaction_while_moving")
        if feats["behavior_anomaly"] > 0.4:
            reasons.append("driving_style_anomaly")
        return reasons
