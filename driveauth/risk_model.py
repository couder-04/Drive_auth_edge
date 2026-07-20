"""Adaptive risk model — GPS/CAN/behaviour/transaction context (§7).

Geo anomaly signal
------------------
``out_of_zone`` is the sole geographic risk feature. ``dist_from_home`` was
retired (Phase 0): it was ``clip01(dist_from_home_km / 50)`` with a
``far_from_home`` reason at feature value 0.6 (30 km), while the synthetic
trainer draws trusted-zone radii from 3–15 km. That scale mismatch flagged
ordinary commute-distance driving as anomalous, and the feature was largely
redundant with ``out_of_zone`` (both derive from the same Haversine call in
``geo.py``). Raw ``RiskContext.dist_from_home_km`` is retained as telemetry;
do not re-add a scaled ``dist_from_home`` feature at the old /50 clip without
re-aligning the reason threshold to the training zone distribution.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth.types import RiskContext, clip01

logger = logging.getLogger("driveauth.risk")

RISK_APPROVE = config.RISK_APPROVE
RISK_REJECT = config.RISK_REJECT

# Hardcoded additive-fallback weights used only when no sidecar file is found
# next to the ONNX model (i.e. a truly fresh install without any trained head).
# When the trainer writes ``risk_gbt_fallback_weights.json`` these are
# overridden per deployment so the fallback reflects what the trained model
# actually learned instead of a hand-tuned prior (review fix #8).
# Phase 0: ``dist_from_home`` retired; its prior 0.12 weight is folded into
# ``out_of_zone`` so the sole geo signal keeps the same total geo mass.
_DEFAULT_FALLBACK_WEIGHTS = {
    "amount_z_scaled": 0.22,   # amount_z is transformed via clip01(x/4) below
    "amount_norm": 0.14,
    "beneficiary_novel": 0.16,
    "out_of_zone": 0.24,
    "night": 0.06,
    "moving_fast": 0.06,
    "ignition_off_anomaly": 0.04,
    "tunnel": 0.02,
    "behavior_anomaly": 0.06,
}


class RiskModel:
    _FEATURE_ORDER = (
        "amount_z",
        "amount_norm",
        "beneficiary_novel",
        "out_of_zone",
        "night",
        "moving_fast",
        "ignition_off_anomaly",
        "tunnel",
        "behavior_anomaly",
    )

    def __init__(self, session=None, fallback_weights=None, importances=None):
        self._session = session
        self._input_name = session.get_inputs()[0].name if session is not None else None
        # Additive-fallback weights (review fix #8). Prefer the sidecar written
        # by the trainer; fall back to the hand-tuned prior for fresh installs.
        self._fallback_weights = fallback_weights or dict(_DEFAULT_FALLBACK_WEIGHTS)
        # Per-feature global importances used to filter which reasons we emit
        # (review fix #9). None -> emit all reasons that pass threshold, i.e.
        # the pre-fix behaviour.
        self._importances = importances

    @classmethod
    def load(cls, store_dir: str, strict: bool | None = None) -> RiskModel:
        """
        Load the trained risk head plus optional trainer sidecars.

        The sidecars are two JSON files the trainer writes next to the ONNX:

          * ``risk_gbt_fallback_weights.json`` -- feature-name -> weight,
            derived from the trained model's importances. Used by the additive
            fallback so that, if the ONNX ever fails to load, the fallback
            still reflects what the trained model learned (review fix #8).
          * ``risk_gbt.json`` -- the trainer's full meta report; used here only
            for its ``feature_importances_gain`` field to drive
            importance-aware reasons (review fix #9).

        ``strict`` (default: ``config.RISK_STRICT_LOAD``) governs what happens
        when ``risk_gbt.onnx`` exists but fails to open. Strict mode raises,
        so a corrupt checkpoint or ORT mismatch is impossible to miss. Non-
        strict logs and degrades to additive -- pre-fix behaviour, retained as
        an opt-out. Missing ONNX (fresh install) always falls through to
        additive, since there's nothing to be strict about.
        """
        if strict is None:
            strict = config.RISK_STRICT_LOAD
        store = Path(store_dir)
        path = store / "risk_gbt.onnx"

        fallback_weights = cls._load_fallback_weights(store)
        importances = cls._load_importances(store)

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
                if strict:
                    # Fix #8: silent degradation to additive is worse than a
                    # loud failure -- an integrator can retry / roll back /
                    # ship a good checkpoint. A silent 0.06-weight
                    # behavior_anomaly path can look normal for weeks.
                    raise RuntimeError(
                        f"RiskModel: {path} exists but failed to load "
                        f"(strict mode on): {exc}"
                    ) from exc
                logger.warning(
                    "RiskModel: load failed (%s) — additive fallback "
                    "(strict mode off)", exc
                )
        else:
            logger.info("RiskModel: no trained model — using additive fallback")
        return cls(session, fallback_weights=fallback_weights, importances=importances)

    @staticmethod
    def _load_fallback_weights(store: Path) -> dict | None:
        p = store / "risk_gbt_fallback_weights.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            # Accept two shapes: raw {name: weight} or nested {weights: {...}}.
            if isinstance(data, dict) and "weights" in data:
                data = data["weights"]
            if not isinstance(data, dict):
                raise ValueError("fallback weights JSON must be an object")
            return {str(k): float(v) for k, v in data.items()}
        except Exception as exc:
            logger.warning(
                "RiskModel: fallback weights sidecar %s unreadable (%s) — "
                "using defaults", p, exc,
            )
            return None

    @staticmethod
    def _load_importances(store: Path) -> dict | None:
        p = store / "risk_gbt.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            imps = data.get("feature_importances_gain")
            if not isinstance(imps, dict):
                return None
            return {str(k): float(v) for k, v in imps.items()}
        except Exception:
            return None

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

        # Additive fallback -- weights come from the sidecar written by the
        # trainer when available (review fix #8), otherwise from
        # _DEFAULT_FALLBACK_WEIGHTS. amount_z uses a special transform
        # (clip01(x/4)) because it's the only feature not already in [0, 1].
        w = self._fallback_weights
        risk = (
            w.get("amount_z_scaled", 0.0) * clip01(feats["amount_z"] / 4.0)
            + w.get("amount_norm", 0.0) * feats["amount_norm"]
            + w.get("beneficiary_novel", 0.0) * feats["beneficiary_novel"]
            + w.get("out_of_zone", 0.0) * feats["out_of_zone"]
            + w.get("night", 0.0) * feats["night"]
            + w.get("moving_fast", 0.0) * feats["moving_fast"]
            + w.get("ignition_off_anomaly", 0.0) * feats["ignition_off_anomaly"]
            + w.get("tunnel", 0.0) * feats["tunnel"]
            + w.get("behavior_anomaly", 0.0) * feats["behavior_anomaly"]
        )
        return clip01(risk), self._reasons(feats)

    # Feature-name -> (threshold, human-readable reason). Threshold only fires
    # a reason when the feature is above it AND the feature has non-negligible
    # global importance in the deployed model (review fix #9).
    _REASON_MAP: dict[str, tuple[float, str]] = {
        "amount_z": (2.0, "amount_far_above_usual"),
        "amount_norm": (0.5, "large_absolute_amount"),
        "beneficiary_novel": (0.5, "first_time_beneficiary"),
        "out_of_zone": (0.5, "unfamiliar_location"),
        "night": (0.5, "unusual_hour"),
        "moving_fast": (0.3, "transaction_while_moving"),
        "behavior_anomaly": (0.4, "driving_style_anomaly"),
    }

    def _reasons(self, feats: dict[str, float]) -> list[str]:
        """
        Emit human-readable reasons for the current call.

        When per-feature importances have been loaded (review fix #9) we only
        surface reasons for features that both (a) exceed their threshold AND
        (b) contribute a non-trivial share of the trained model's total gain.
        This keeps ``reasons`` consistent with what the deployed model
        actually cares about -- e.g. we stop emitting ``unusual_hour`` on
        risk=0.9 calls when the model's own gain attribution for ``night`` is
        near zero. When importances are absent (fresh install / no sidecar)
        we fall back to threshold-only, matching pre-fix behaviour.
        """
        reasons: list[str] = []
        min_share = 0.02  # 2% of total gain -- generous, only filters truly dead features
        total_imp = None
        if self._importances:
            total_imp = float(sum(self._importances.values())) or None
        for feat_name, (thr, label) in self._REASON_MAP.items():
            val = feats.get(feat_name, 0.0)
            if val <= thr:
                continue
            if total_imp is not None:
                share = self._importances.get(feat_name, 0.0) / total_imp
                if share < min_share:
                    continue
            reasons.append(label)
        return reasons
