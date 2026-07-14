"""FastAPI application — DriveAuth pipeline API + dashboard."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from driveauth import DriveAuth
from driveauth.matchers.mock import (
    MOCK_FACE_DIM,
    MOCK_FINGER_DIM,
    MOCK_VOICE_DIM,
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from dashboard.dashboard import render_dashboard

_STORE = os.getenv("DRIVEAUTH_DASHBOARD_STORE", "")
_auth: DriveAuth | None = None


def _fake_audio(seconds: float = 1.5, sr: int = 16_000) -> np.ndarray:
    # Speech-like energy variation so QualityGate SNR passes (pure sine ≈ 0 dB).
    n = int(sr * seconds)
    t = np.linspace(0, seconds, n, dtype=np.float32)
    rng = np.random.default_rng(0)
    envelope = 0.05 + 0.15 * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))
    speech = envelope * np.sin(2 * np.pi * 180 * t)
    noise = 0.005 * rng.standard_normal(n).astype(np.float32)
    return (speech + noise).astype(np.float32)


def _load_auth(*, mature: bool = True) -> DriveAuth:
    store = _STORE or tempfile.mkdtemp(prefix="driveauth_dashboard_")
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    if mature:
        auth._profile.seed_mature()
    return auth


def get_auth() -> DriveAuth:
    global _auth
    if _auth is None:
        # Default to a mature driver so the ACCEPT scenario can actually ACCEPT.
        # Bootstrap force_step_up otherwise overrides every happy-path micro pay.
        _auth = _load_auth(mature=True)
    return _auth


def reset_auth(*, mature: bool = True) -> DriveAuth:
    global _auth
    _auth = _load_auth(mature=mature)
    return _auth


class MockScores(BaseModel):
    voice: float = Field(0.92, ge=0.0, le=1.0)
    face: float = Field(0.88, ge=0.0, le=1.0)
    finger: float | None = Field(0.85, ge=0.0, le=1.0)
    behavioral: float = Field(0.95, ge=0.0, le=1.0)


class VehicleContext(BaseModel):
    speed_kmh: float = 0.0
    in_trusted_zone: bool = True
    dist_from_home_km: float = 0.0
    is_tunnel: bool = False
    ignition_on: bool = True
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_accuracy_m: float = 50.0


class AuthenticateRequest(BaseModel):
    amount: float = Field(150.0, ge=0.0)
    beneficiary: str = "Starbucks"
    beneficiary_known: bool = True
    is_guest: bool = False
    action: str = "pay"
    currency: str = "INR"
    channel: str = "dashboard"
    mock_scores: MockScores = Field(default_factory=MockScores)
    context: VehicleContext = Field(default_factory=VehicleContext)


def _result_payload(result) -> dict[str, Any]:
    return {
        "decision": result.decision.value,
        "legacy_decision": result.legacy_decision,
        "trust_score": result.trust_score,
        "risk_score": result.risk_score,
        "confidence_score": result.confidence_score,
        "tier": result.tier,
        "policy_rule": result.policy_rule,
        "fraud_state": result.fraud_state,
        "step_up_method": result.step_up_method,
        "explanations": result.explanations,
        "modality_scores": result.modality_scores,
        "active_thresholds": result.active_thresholds,
        "ood_flags": result.ood_flags,
    }


def _apply_mock_scores(auth: DriveAuth, scores: MockScores) -> None:
    auth._engine._m.voice = MockVoiceMatcher(score=scores.voice)
    auth._engine._m.face = MockFaceMatcher(score=scores.face)
    auth._engine._m.finger = MockFingerMatcher(score=scores.finger)
    auth._engine._m.behavioral = MockBehavioralMonitor(score=scores.behavioral)
    auth._engine._m.fingerprint_available = scores.finger is not None
    # Keep OOD baselines aligned with mock embedding dims (MobileFaceNet=512).
    from driveauth.ood_detector import OODDetector

    auth._engine._ood = OODDetector.seed_baselines(
        auth._store,
        auth.driver_id,
        voice_dim=MOCK_VOICE_DIM,
        face_dim=MOCK_FACE_DIM,
        finger_dim=MOCK_FINGER_DIM,
    )


app = FastAPI(
    title="DriveAuth Edge Dashboard",
    description="Test and monitor the Trust/Risk-separated authorization pipeline.",
    version="0.2.0",
)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return render_dashboard()


@app.get("/api/status")
def status() -> dict[str, Any]:
    auth = get_auth()
    mature = auth._profile.is_mature()
    rigor = auth._fraud.effective_rigor(mature)
    return {
        "store_dir": auth._store,
        "driver_id": auth.driver_id,
        "fraud_state": auth._fraud.effective_state(mature).value,
        "fraud_ladder": auth._fraud.state.value,
        "profile_mature": mature,
        "profile_maturity": auth._profile.maturity_reason(),
        "fraud_rigor": rigor,
        "enabled": auth._enabled,
        "use_mock": True,
    }


@app.post("/api/context")
def update_context(ctx: VehicleContext) -> dict[str, str]:
    auth = get_auth()
    data = {k: v for k, v in ctx.model_dump().items() if v is not None}
    auth.update_vehicle_context(**data)
    auth.update_behavioral(
        {"vehicle_speed_kmh": ctx.speed_kmh, "ignition_on": float(ctx.ignition_on)}
    )
    return {"status": "ok"}


@app.post("/api/authenticate")
def authenticate(req: AuthenticateRequest) -> dict[str, Any]:
    auth = get_auth()
    _apply_mock_scores(auth, req.mock_scores)
    ctx = req.context.model_dump()
    # Drop null GPS so RiskContext keeps Optional defaults cleanly
    ctx = {k: v for k, v in ctx.items() if v is not None}
    auth.update_vehicle_context(**ctx)
    auth.update_behavioral(
        {
            "vehicle_speed_kmh": req.context.speed_kmh,
            "ignition_on": float(req.context.ignition_on),
        }
    )

    audio = _fake_audio()
    result = auth.authenticate(
        audio_np=audio,
        amount=req.amount,
        beneficiary=req.beneficiary,
        action=req.action,
        currency=req.currency,
        channel=req.channel,
        beneficiary_known=req.beneficiary_known,
        is_guest=req.is_guest,
        event="dashboard_auth",
    )
    return _result_payload(result)


@app.get("/api/audit")
def audit(limit: int = 50) -> list[dict[str, Any]]:
    auth = get_auth()
    path = Path(auth._store) / "audit" / "driveauth_events.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(entries))


@app.post("/api/fraud/soft-flag")
def fraud_soft_flag(reason: str = "dashboard_test") -> dict[str, Any]:
    auth = get_auth()
    state = auth._fraud.record_soft_flag(reason)
    return {"fraud_state": state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/fraud/clean")
def fraud_clean() -> dict[str, Any]:
    auth = get_auth()
    state = auth._fraud.record_clean()
    return {"fraud_state": state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/fraud/reset")
def fraud_reset() -> dict[str, Any]:
    auth = get_auth()
    auth._fraud.reset()
    return {"fraud_state": auth._fraud.state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/reset")
def reset_session(mature: bool = True) -> dict[str, Any]:
    auth = reset_auth(mature=mature)
    return {
        "status": "ok",
        "store_dir": auth._store,
        "profile_mature": auth._profile.is_mature(),
        "fraud_state": auth._fraud.effective_state(auth._profile.is_mature()).value,
    }


@app.post("/api/profile/mature")
def profile_mature() -> dict[str, Any]:
    auth = get_auth()
    auth._profile.seed_mature()
    mature = True
    return {
        "profile_mature": mature,
        "profile_maturity": auth._profile.maturity_reason(),
        "fraud_state": auth._fraud.effective_state(mature).value,
    }


@app.post("/api/profile/bootstrap")
def profile_bootstrap() -> dict[str, Any]:
    auth = get_auth()
    auth._profile.reset_bootstrap()
    mature = False
    return {
        "profile_mature": mature,
        "profile_maturity": auth._profile.maturity_reason(),
        "fraud_state": auth._fraud.effective_state(mature).value,
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": "accept_micro",
            "label": "Micro payment (ACCEPT)",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=50.0, beneficiary_known=True
            ).model_dump(),
        },
        {
            "id": "bootstrap_stepup",
            "label": "New driver bootstrap (STEP_UP)",
            "profile": "bootstrap",
            "request": AuthenticateRequest(
                amount=50.0, beneficiary_known=True
            ).model_dump(),
        },
        {
            "id": "high_value_stepup",
            "label": "High value (STEP_UP)",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=75_000.0, beneficiary_known=False, beneficiary="new_merchant"
            ).model_dump(),
        },
        {
            "id": "low_trust_reject",
            "label": "Low biometrics (REJECT)",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=150.0,
                mock_scores=MockScores(voice=0.40, face=0.40, finger=0.40),
            ).model_dump(),
        },
        {
            "id": "risky_context",
            "label": "Risky context + moving",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=5_000.0,
                beneficiary_known=False,
                context=VehicleContext(
                    speed_kmh=95.0, in_trusted_zone=False, dist_from_home_km=45.0
                ),
            ).model_dump(),
        },
    ]
