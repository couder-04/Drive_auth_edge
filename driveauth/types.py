"""Shared dataclasses and enums — dependency-free except numpy."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class Decision(str, enum.Enum):
    ACCEPT = "ACCEPT"
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"
    REJECT = "REJECT"

    def legacy(self) -> str:
        return {
            Decision.ACCEPT: "pass",
            Decision.STEP_UP_REQUIRED: "step_up",
            Decision.REJECT: "deny",
        }[self]


@dataclass
class ModalityResult:
    score: float | None
    confident: bool
    latency_ms: float = 0.0
    quality: float = 1.0
    ood: bool = False
    embedding: np.ndarray | None = None
    # False when the sensor/model itself is unavailable (not merely a low score).
    available: bool = True


@dataclass
class QualityFlags:
    voice_ok: bool = True
    face_ok: bool = True
    finger_ok: bool = True
    voice_q: float = 1.0
    face_q: float = 1.0
    finger_q: float = 1.0
    hardware_fault: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class RiskContext:
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_accuracy_m: float = 50.0
    speed_kmh: float = 0.0
    ignition_on: bool = True
    is_tunnel: bool = False
    time_hour: float = 12.0
    amount: float = 0.0
    currency: str = "INR"
    beneficiary: str = ""
    action: str = ""
    channel: str = "voice"
    beneficiary_known: bool = False
    behavioral_score: float | None = None
    behavioral_available: bool = True
    amount_mean: float = 0.0
    amount_std: float = 0.0
    dist_from_home_km: float = 0.0
    in_trusted_zone: bool = True


@dataclass
class DriveAuthResult:
    trust_score: float
    risk_score: float
    confidence_score: float
    decision: Decision
    tier: str = "standard"
    explanations: list[str] = field(default_factory=list)
    step_up_method: str | None = None
    step_up_fallback: str | None = None
    policy_rule: str = ""
    fraud_state: str = "normal"
    modality_scores: dict[str, Any] = field(default_factory=dict)
    active_thresholds: dict[str, float] = field(default_factory=dict)
    ood_flags: dict[str, bool] = field(default_factory=dict)
    is_payment: bool = False
    amount: float = 0.0
    currency: str = "INR"
    beneficiary: str = ""
    action: str = ""
    channel: str = "voice"
    session_id: str = ""
    driver_id: str = ""

    @property
    def score(self) -> float:
        return self.trust_score

    @property
    def legacy_decision(self) -> str:
        return self.decision.legacy()


def clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))
