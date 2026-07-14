"""FastAPI application — DriveAuth pipeline API + dashboard."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from driveauth import DriveAuth
from driveauth.enrollment import (
    enroll_driver,
    ensure_driver_layout,
    enrollment_status,
    list_enroll_images,
    list_enroll_wavs,
    save_face_jpeg,
    save_voice_wav_bytes,
    validate_driver_id,
)
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
from dashboard.register import render_register

_ROOT = Path(__file__).resolve().parents[1]
_STORE = os.getenv("DRIVEAUTH_DASHBOARD_STORE", "")
_REGISTER_STORE = os.getenv(
    "DRIVEAUTH_REGISTER_STORE",
    str(_ROOT / "driveauth_store_phase2a"),
)
_DATA_ROOT = Path(os.getenv("DRIVEAUTH_DATA_ROOT", str(_ROOT / "data")))
_auth: DriveAuth | None = None


def _register_store() -> Path:
    return Path(_REGISTER_STORE).expanduser().resolve()


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


def _pipeline_trace(result) -> dict[str, Any]:
    """Derive a stage-by-stage flow for the live dashboard visualization."""
    expl = list(result.explanations or [])
    mods = result.modality_scores or {}
    probed: list[str] = []
    for e in expl:
        if e.startswith("probed_"):
            raw = e.removeprefix("probed_")
            if raw and raw != "none":
                probed = [p for p in raw.split("+") if p]
            break

    def _mod_score(name: str) -> float | None:
        block = mods.get(name) or {}
        if not isinstance(block, dict):
            return None
        val = block.get("score")
        return float(val) if val is not None else None

    ladder_stages: list[dict[str, Any]] = []
    order = ("voice", "face", "finger")
    accept_mod: str | None = None
    for mod in order:
        # Prefer "ladder_accept_voice_score_…" over "ladder_accept_bar_voice_…"
        if any(e.startswith(f"ladder_accept_{mod}_") for e in expl):
            accept_mod = mod
            break
    if accept_mod is None and result.policy_rule:
        for mod in order:
            if f"ladder_accept_{mod}" in result.policy_rule:
                accept_mod = mod
                break

    accept_idx = order.index(accept_mod) if accept_mod in order else None
    last_probed = probed[-1] if probed else None
    decided_reject = result.decision.value == "REJECT"

    for mod in order:
        score = _mod_score(mod)
        idx = order.index(mod)
        if accept_idx is not None and idx > accept_idx:
            status, detail = "skipped", "early-stop · not probed"
        elif mod in probed:
            if accept_mod == mod:
                status = "accept"
                detail = f"≥ bar · {score:.3f}" if score is not None else "accepted"
            elif decided_reject and mod == last_probed:
                status = "reject"
                detail = f"exhausted · {score:.3f}" if score is not None else "exhausted"
            else:
                status = "escalate"
                detail = f"below bar · {score:.3f}" if score is not None else "no score"
        elif accept_mod is not None:
            status, detail = "skipped", "not needed"
        else:
            status, detail = "idle", "not reached"
        ladder_stages.append(
            {"id": mod, "label": mod.title(), "status": status, "score": score, "detail": detail}
        )

    hard_gate = None
    for key, label in (
        ("fraud_locked", "Fraud lock"),
        ("risk_above_hard_ceiling", "Risk ceiling"),
        ("guest_mode_requires_pin", "Guest PIN"),
    ):
        if any(key in e for e in expl):
            hard_gate = label
            break

    decision = result.decision.value
    stages = [
        {
            "id": "intent",
            "label": "Intent",
            "status": "done",
            "detail": f"{result.action or 'pay'} · {result.currency} {result.amount:g}",
        },
        {
            "id": "risk",
            "label": "Risk model",
            "status": "done",
            "detail": f"risk {result.risk_score:.3f} · tier {result.tier}",
        },
        {
            "id": "fraud",
            "label": "Fraud ladder",
            "status": "block" if hard_gate == "Fraud lock" else "done",
            "detail": hard_gate if hard_gate == "Fraud lock" else (result.fraud_state or "normal"),
        },
        {
            "id": "ladder",
            "label": "Bio ladder",
            "status": (
                "block"
                if decision == "REJECT" and hard_gate is None
                else "accept"
                if decision == "ACCEPT"
                else "stepup"
                if decision == "STEP_UP_REQUIRED"
                else "done"
            ),
            "detail": (
                f"probed {' → '.join(probed) if probed else '—'}"
                + (f" · early-stop {accept_mod}" if accept_mod else "")
            ),
            "rungs": ladder_stages,
        },
        {
            "id": "policy",
            "label": "Policy",
            "status": (
                "accept"
                if decision == "ACCEPT"
                else "stepup"
                if decision == "STEP_UP_REQUIRED"
                else "block"
            ),
            "detail": result.policy_rule or "—",
        },
        {
            "id": "decision",
            "label": "Decision",
            "status": (
                "accept"
                if decision == "ACCEPT"
                else "stepup"
                if decision == "STEP_UP_REQUIRED"
                else "block"
            ),
            "detail": decision,
        },
    ]

    return {
        "stages": stages,
        "probed": probed,
        "accept_modality": accept_mod,
        "hard_gate": hard_gate,
        "path_summary": (
            hard_gate
            or (
                f"{' → '.join(m.title() for m in probed)} → {decision}"
                if probed
                else decision
            )
        ),
    }


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
        "pipeline": _pipeline_trace(result),
        "amount": result.amount,
        "currency": result.currency,
        "beneficiary": result.beneficiary,
        "action": result.action,
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
    description="Live Trust/Risk/Confidence pipeline tester with Nova I/O contract.",
    version="0.3.0",
)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return render_dashboard()


@app.get("/register", response_class=HTMLResponse)
def register_page() -> str:
    return render_register()


class RegisterDriverRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=32)


@app.get("/api/register/status")
def register_status(driver_id: str = "driver2") -> dict[str, Any]:
    try:
        return enrollment_status(_DATA_ROOT, _register_store(), driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/register/init")
def register_init(req: RegisterDriverRequest) -> dict[str, Any]:
    try:
        root = ensure_driver_layout(_DATA_ROOT, req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "driver_id": validate_driver_id(req.driver_id),
        "data_dir": str(root),
        **enrollment_status(_DATA_ROOT, _register_store(), req.driver_id),
    }


@app.post("/api/register/face")
async def register_face(
    driver_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        validate_driver_id(driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image upload")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="image too large")
    path = save_face_jpeg(_DATA_ROOT, driver_id, raw, split="enroll")
    return {
        "status": "ok",
        "path": str(path.relative_to(_DATA_ROOT)),
        **enrollment_status(_DATA_ROOT, _register_store(), driver_id),
    }


@app.post("/api/register/voice")
async def register_voice(
    driver_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        validate_driver_id(driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="audio too large")
    try:
        path = save_voice_wav_bytes(_DATA_ROOT, driver_id, raw, split="enroll")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid WAV: {exc}") from exc
    return {
        "status": "ok",
        "path": str(path.relative_to(_DATA_ROOT)),
        **enrollment_status(_DATA_ROOT, _register_store(), driver_id),
    }


@app.post("/api/register/complete")
def register_complete(req: RegisterDriverRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data_dir = _DATA_ROOT / driver_id
    store = _register_store()
    try:
        result = enroll_driver(store, data_dir, driver_id, require_minimums=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", **result}


@app.post("/api/register/clear")
def register_clear(req: RegisterDriverRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data_dir = _DATA_ROOT / driver_id
    for path in list_enroll_images(data_dir) + list_enroll_wavs(data_dir):
        path.unlink(missing_ok=True)
    return {
        "status": "ok",
        **enrollment_status(_DATA_ROOT, _register_store(), driver_id),
    }


@app.get("/api/register/preview/face/{driver_id}/{filename}")
def register_face_preview(driver_id: str, filename: str) -> FileResponse:
    try:
        driver_id = validate_driver_id(driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = (_DATA_ROOT / driver_id / "face" / "enroll" / safe).resolve()
    enroll_root = (_DATA_ROOT / driver_id / "face" / "enroll").resolve()
    if not path.is_relative_to(enroll_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/jpeg")


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
            "id": "bootstrap_ladder",
            "label": "New driver bootstrap (ladder ACCEPT on strong voice)",
            "profile": "bootstrap",
            "request": AuthenticateRequest(
                amount=50.0, beneficiary_known=True
            ).model_dump(),
        },
        {
            "id": "high_value_ladder",
            "label": "High value (ladder ACCEPT if voice/face strong)",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=75_000.0, beneficiary_known=False, beneficiary="new_merchant"
            ).model_dump(),
        },
        {
            "id": "escalate_face",
            "label": "Low voice → Face ACCEPT",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=150.0,
                mock_scores=MockScores(voice=0.40, face=0.90, finger=0.40),
            ).model_dump(),
        },
        {
            "id": "low_trust_reject",
            "label": "Low biometrics (REJECT after ladder)",
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
        {
            "id": "guest_stepup",
            "label": "Guest mode (STEP_UP)",
            "profile": "mature",
            "request": AuthenticateRequest(
                amount=150.0,
                is_guest=True,
                beneficiary_known=True,
            ).model_dump(),
        },
    ]
