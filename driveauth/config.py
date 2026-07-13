"""Policy thresholds loaded from ``policy.yaml`` with ``${ENV:default}`` placeholders.

``DRIVEAUTH_*`` env vars override placeholder defaults. ``NOVA_*`` aliases remain
for Nova AI drop-in. Point ``DRIVEAUTH_POLICY_FILE`` at another YAML to swap the
whole pack without rebuilding.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "PyYAML is required to load driveauth/policy.yaml — "
        "install with: pip install 'driveauth-edge' (or PyYAML)"
    ) from exc

_PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::(.*))?\}$", re.DOTALL)

# DRIVEAUTH_* → NOVA_* legacy aliases (only when the DRIVEAUTH_ name is unset).
_LEGACY_ALIASES: dict[str, str] = {
    "DRIVEAUTH_RISK_APPROVE": "NOVA_RISK_APPROVE",
    "DRIVEAUTH_RISK_REJECT": "NOVA_RISK_REJECT",
    "DRIVEAUTH_TRUST_ACCEPT_MICRO": "NOVA_TRUST_ACCEPT_MICRO",
    "DRIVEAUTH_TRUST_ACCEPT_STD": "NOVA_TRUST_ACCEPT_STD",
    "DRIVEAUTH_TRUST_ACCEPT_HIGH": "NOVA_TRUST_ACCEPT_HIGH",
    "DRIVEAUTH_TRUST_REJECT": "NOVA_TRUST_REJECT",
    "DRIVEAUTH_CONF_FLOOR": "NOVA_CONF_FLOOR",
    "DRIVEAUTH_TIER_MICRO_MAX": "NOVA_TIER_MICRO_MAX",
    "DRIVEAUTH_TIER_HIGH_MIN": "NOVA_TIER_HIGH_MIN",
    "DRIVEAUTH_TIER_GUEST_MAX": "NOVA_TIER_GUEST_MAX",
    "DRIVEAUTH_POLICY_VERSION": "NOVA_POLICY_VERSION",
    "DRIVEAUTH_FRAUD_LADDER_DECAY_HOURS": "NOVA_FRAUD_LADDER_DECAY_HOURS",
    "DRIVEAUTH_FRAUD_CLEAN_STREAK": "NOVA_FRAUD_CLEAN_STREAK",
    "DRIVEAUTH_OTP_TTL_S": "NOVA_OTP_TTL_S",
    "DRIVEAUTH_OTP_LENGTH": "NOVA_OTP_LENGTH",
    "DRIVEAUTH_OTP_MAX_TRIES": "NOVA_OTP_MAX_TRIES",
    "DRIVEAUTH_OTP_PROVIDER_URL": "NOVA_OTP_PROVIDER_URL",
    "DRIVEAUTH_OTP_PROVIDER_TIMEOUT_S": "NOVA_OTP_PROVIDER_TIMEOUT_S",
    "DRIVEAUTH_STEP_UP_RETRIES": "NOVA_STEP_UP_RETRIES",
    "DRIVEAUTH_FINGERPRINT_AVAILABLE": "NOVA_FINGERPRINT_AVAILABLE",
    "DRIVEAUTH_TRUST_W_VOICE": "NOVA_TRUST_W_VOICE",
    "DRIVEAUTH_TRUST_W_FACE": "NOVA_TRUST_W_FACE",
    "DRIVEAUTH_TRUST_W_FINGER": "NOVA_TRUST_W_FINGER",
    "DRIVEAUTH_PIN_MIN_LEN": "NOVA_PIN_MIN_LEN",
    "DRIVEAUTH_ORCH_UNCERTAINTY": "NOVA_ORCH_UNCERTAINTY",
    "DRIVEAUTH_Q_VOICE_MIN_SNR": "NOVA_Q_VOICE_MIN_SNR",
    "DRIVEAUTH_Q_VOICE_CLIP_FRAC": "NOVA_Q_VOICE_CLIP_FRAC",
    "DRIVEAUTH_Q_VOICE_MIN_SEC": "NOVA_Q_VOICE_MIN_SEC",
    "DRIVEAUTH_Q_FACE_MIN_SHARP": "NOVA_Q_FACE_MIN_SHARP",
    "DRIVEAUTH_Q_FACE_MIN_BRIGHT": "NOVA_Q_FACE_MIN_BRIGHT",
    "DRIVEAUTH_Q_FACE_MAX_BRIGHT": "NOVA_Q_FACE_MAX_BRIGHT",
    "DRIVEAUTH_Q_FINGER_MIN_CONTACT": "NOVA_Q_FINGER_MIN_CONTACT",
    "DRIVEAUTH_OOD_Z_THRESH": "NOVA_OOD_Z_THRESH",
    "DRIVEAUTH_OOD_COSINE_THRESH": "NOVA_OOD_COSINE_THRESH",
    "DRIVEAUTH_IR_CAMERA_INDEX": "NOVA_IR_CAMERA_INDEX",
    "DRIVEAUTH_FINGER_SOCKET": "NOVA_FINGER_SOCKET",
}


def _env_lookup(name: str) -> str | None:
    v = os.getenv(name)
    if v is not None:
        return v
    legacy = _LEGACY_ALIASES.get(name)
    if legacy:
        return os.getenv(legacy)
    # Generic NOVA_* mirror for any DRIVEAUTH_* not listed above.
    if name.startswith("DRIVEAUTH_"):
        return os.getenv("NOVA_" + name[len("DRIVEAUTH_") :])
    return None


def _resolve_placeholders(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _resolve_placeholders(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_placeholders(v) for v in node]
    if isinstance(node, str):
        m = _PLACEHOLDER.match(node.strip())
        if not m:
            return node
        name, default = m.group(1), m.group(2)
        found = _env_lookup(name)
        if found is not None:
            return found
        return "" if default is None else default
    return node


def _as_float(v: Any) -> float:
    return float(v)


def _as_int(v: Any) -> int:
    return int(float(v))


def _as_bool01(v: Any) -> bool:
    """Treat '1' / 'true' / 'yes' / True as enabled."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _policy_path() -> Path:
    override = os.getenv("DRIVEAUTH_POLICY_FILE") or os.getenv("NOVA_POLICY_FILE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "policy.yaml"


def load_policy(path: Path | None = None) -> dict[str, Any]:
    p = path or _policy_path()
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"policy file must be a mapping: {p}")
    return _resolve_placeholders(raw)


_P = load_policy()

# ── Public constants (same names as before — callers unchanged) ──────────────

POLICY_VERSION = str(_P["version"])

RISK_APPROVE = _as_float(_P["risk"]["approve"])
RISK_REJECT = _as_float(_P["risk"]["reject"])

TRUST_ACCEPT_MICRO = _as_float(_P["trust"]["accept_micro"])
TRUST_ACCEPT_STD = _as_float(_P["trust"]["accept_standard"])
TRUST_ACCEPT_HIGH = _as_float(_P["trust"]["accept_high"])
TRUST_REJECT = _as_float(_P["trust"]["reject"])
TRUST_W_VOICE = _as_float(_P["trust"]["weights"]["voice"])
TRUST_W_FACE = _as_float(_P["trust"]["weights"]["face"])
TRUST_W_FINGER = _as_float(_P["trust"]["weights"]["finger"])

CONF_FLOOR = _as_float(_P["confidence"]["floor"])
CONF_DISAGREE_SPREAD = _as_float(_P["confidence"]["disagreement_spread"])
CONF_SINGLE_AGREE = _as_float(_P["confidence"]["single_modality_agreement"])
CONF_LOW_QUALITY = _as_float(_P["confidence"]["low_quality_bar"])
CONF_OOD_MISSING = _as_float(_P["confidence"]["ood_missing_penalty"])
CONF_BEHAVIOR_MISSING = _as_float(_P["confidence"]["behavioral_missing_penalty"])
CONF_SENSOR_GAP = _as_float(_P["confidence"]["sensor_gap_penalty"])
CONF_HW_FAULT = _as_float(_P["confidence"]["hardware_fault_penalty"])
CONF_W_AGREE = _as_float(_P["confidence"]["w_agreement"])
CONF_W_QUALITY = _as_float(_P["confidence"]["w_quality"])
CONF_W_OOD = _as_float(_P["confidence"]["w_ood"])

TIER_MICRO_MAX = _as_float(_P["tiers"]["micro_max"])
TIER_HIGH_MIN = _as_float(_P["tiers"]["high_min"])
TIER_GUEST_MAX = _as_float(_P["tiers"]["guest_max"])

FRAUD_LADDER_DECAY_HOURS = _as_float(_P["fraud"]["decay_hours"])
FRAUD_CLEAN_STREAK = _as_int(_P["fraud"]["clean_streak"])
FRAUD_RIGOR: dict[str, dict[str, Any]] = {
    k: dict(v) for k, v in _P["fraud"]["rigor"].items()
}

OTP_TTL_S = _as_float(_P["otp"]["ttl_s"])
OTP_LENGTH = _as_int(_P["otp"]["length"])
OTP_MAX_TRIES = _as_int(_P["otp"]["max_tries"])
OTP_PROVIDER_URL = str(_P["otp"]["provider_url"])
OTP_PROVIDER_TIMEOUT_S = _as_float(_P["otp"]["provider_timeout_s"])

STEP_UP_RETRIES = _as_int(_P["step_up"]["retries"])
PIN_MIN_LEN = _as_int(_P["step_up"]["pin_min_len"])
FALLBACK_MIN_TRUST = _as_float(_P["step_up"]["fallback_min_trust"])

FINGERPRINT_AVAILABLE = _as_bool01(_P["hardware"]["fingerprint_available"])
IR_CAMERA_INDEX = _as_int(_P["hardware"]["ir_camera_index"])
FINGER_SOCKET = str(_P["hardware"]["finger_socket"])

ESCALATION_ENABLED = _as_bool01(_P["escalation"]["enabled"])
ESCALATION_CONSTANT_TIME_MS = _as_float(_P["escalation"]["constant_time_ms"])

BOOTSTRAP_MIN_TXNS = _as_int(_P["bootstrap"]["min_txns"])
BOOTSTRAP_MIN_DAYS = _as_float(_P["bootstrap"]["min_days"])
PROFILE_STALE_DAYS = _as_float(_P["bootstrap"]["stale_days"])
BOOTSTRAP_AMOUNT_CAP = _as_float(_P["bootstrap"]["amount_cap"])
PROFILE_SCHEMA_VERSION = _as_int(_P["bootstrap"]["schema_version"])

DECISION_CACHE_TTL_S = _as_float(_P["cache"]["decision_ttl_s"])

Q_VOICE_MIN_SNR = _as_float(_P["quality"]["voice_min_snr_db"])
Q_VOICE_CLIP_FRAC = _as_float(_P["quality"]["voice_clip_frac"])
Q_VOICE_MIN_SEC = _as_float(_P["quality"]["voice_min_seconds"])
Q_FACE_MIN_SHARP = _as_float(_P["quality"]["face_min_sharpness"])
Q_FACE_MIN_BRIGHT = _as_float(_P["quality"]["face_min_bright"])
Q_FACE_MAX_BRIGHT = _as_float(_P["quality"]["face_max_bright"])
FACE_MIN_FRAC = _as_float(_P["quality"]["face_min_frac"])
Q_FINGER_MIN_CONTACT = _as_float(_P["quality"]["finger_min_contact"])

OOD_Z_THRESH = _as_float(_P["ood"]["z_thresh"])
OOD_COSINE_THRESH = _as_float(_P["ood"]["cosine_thresh"])

ORCH_UNCERTAINTY = _as_float(_P["orchestrator"]["uncertainty_thresh"])

# Geo / home-learning (review fix #3).
TRUSTED_ZONE_RADIUS_KM = _as_float(_P["geo"]["trusted_zone_radius_km"])
HOME_LEARN_MIN_SAMPLES = _as_int(_P["geo"]["home_learn_min_samples"])
HOME_LEARN_MAX_ACCURACY_M = _as_float(_P["geo"]["home_learn_max_accuracy_m"])

# Risk-model load strictness (review fix #8). When true, a present-but-corrupt
# risk_gbt.onnx causes RiskModel.load to raise instead of silently degrading
# to the additive fallback -- a defensive default for a safety-critical head.
RISK_STRICT_LOAD = _as_bool01(_P["risk"]["strict_load"])

# Raw resolved tree for audit / dashboard introspection.
POLICY: dict[str, Any] = _P
