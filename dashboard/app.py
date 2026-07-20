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
from driveauth.audio_io import wav_bytes_to_float32
from driveauth.enrollment import (
    enroll_driver,
    ensure_driver_layout,
    enrollment_status,
    list_enroll_images,
    list_enroll_wavs,
    list_registered_drivers,
    save_face_jpeg,
    save_voice_wav_bytes,
    validate_driver_id,
)
from driveauth.consent import ConsentRequiredError, record_consent
from driveauth.purge import purge_driver
from driveauth.matchers.mock import (
    MOCK_FACE_DIM,
    MOCK_FINGER_DIM,
    MOCK_VOICE_DIM,
    MockBehavioralMonitor,
    MockFaceMatcher,
    MockFingerMatcher,
    MockVoiceMatcher,
)
from driveauth.profile_store import ProfileStore
from driveauth.secrets import (
    ensure_secrets_loaded,
    get_secret,
    google_maps_key,
    openrouter_configured,
)
from driveauth.standalone_session import IntentSlots, process_audio, process_transcript
from dashboard.dashboard import render_dashboard
from dashboard.fleet import render_fleet
from dashboard.register import render_register

ensure_secrets_loaded()

_ROOT = Path(__file__).resolve().parents[1]
_auth: DriveAuth | None = None
_auth_key: tuple[str, str, bool] | None = None


def _data_root() -> Path:
    return Path(get_secret("DRIVEAUTH_DATA_ROOT", str(_ROOT / "data"))).expanduser().resolve()


def _unified_store() -> Path:
    """Register + auth share one store (standalone product path)."""
    raw = (
        get_secret("DRIVEAUTH_DASHBOARD_STORE")
        or get_secret("DRIVEAUTH_REGISTER_STORE")
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    phase2a = _ROOT / "driveauth_store_phase2a"
    if phase2a.is_dir():
        return phase2a.resolve()
    tmp = Path(tempfile.mkdtemp(prefix="driveauth_dashboard_"))
    return tmp


def _register_store() -> Path:
    return _unified_store()


def _default_driver() -> str:
    return get_secret("DRIVEAUTH_DEFAULT_DRIVER", "driver1") or "driver1"


def _want_mock() -> bool:
    return get_secret("DRIVEAUTH_USE_MOCK", "0").strip() == "1"


def _fake_audio(seconds: float = 1.5, sr: int = 16_000) -> np.ndarray:
    # Speech-like energy variation so QualityGate SNR passes (pure sine ≈ 0 dB).
    n = int(sr * seconds)
    t = np.linspace(0, seconds, n, dtype=np.float32)
    rng = np.random.default_rng(0)
    envelope = 0.05 + 0.15 * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))
    speech = envelope * np.sin(2 * np.pi * 180 * t)
    noise = 0.005 * rng.standard_normal(n).astype(np.float32)
    return (speech + noise).astype(np.float32)


def _load_auth(
    *,
    mature: bool = True,
    driver_id: str | None = None,
    use_mock: bool | None = None,
) -> DriveAuth:
    store = str(_unified_store())
    did = validate_driver_id(driver_id or _default_driver())
    mock = _want_mock() if use_mock is None else use_mock
    auth = DriveAuth.load(store_dir=store, driver_id=did, use_mock_matchers=mock)
    if mature:
        auth._profile.seed_mature()
    return auth


def get_auth(
    driver_id: str | None = None,
    *,
    use_mock: bool | None = None,
    mature: bool = True,
) -> DriveAuth:
    global _auth, _auth_key
    did = validate_driver_id(driver_id or _default_driver())
    mock = _want_mock() if use_mock is None else use_mock
    store = str(_unified_store())
    key = (store, did, mock)
    if _auth is None or _auth_key != key:
        _auth = _load_auth(mature=mature, driver_id=did, use_mock=mock)
        _auth_key = key
    return _auth


def reset_auth(
    *,
    mature: bool = True,
    driver_id: str | None = None,
    use_mock: bool | None = None,
) -> DriveAuth:
    global _auth, _auth_key
    _auth = None
    _auth_key = None
    return get_auth(driver_id, use_mock=use_mock, mature=mature)


def _decode_face_jpeg(raw: bytes) -> np.ndarray:
    try:
        import cv2
    except ImportError as exc:
        raise HTTPException(
            status_code=503, detail="opencv required for face: pip install -e '.[face]'"
        ) from exc
    arr = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(status_code=400, detail="could not decode face JPEG")
    return bgr


def _apply_finger_manual(auth: DriveAuth, finger: float | None) -> None:
    auth._engine._m.finger = MockFingerMatcher(score=finger)
    auth._engine._m.fingerprint_available = finger is not None
    if not hasattr(auth._engine._m, "behavioral") or auth._engine._m.behavioral is None:
        auth._engine._m.behavioral = MockBehavioralMonitor(score=0.95)


def _profile_for(driver_id: str) -> ProfileStore:
    store = _unified_store()
    did = validate_driver_id(driver_id)
    return ProfileStore(store / "profiles" / f"{did}.json", did)


def _list_enrolled_drivers() -> list[dict[str, Any]]:
    store = _unified_store()
    faces = store / "faces"
    out: list[dict[str, Any]] = []
    if faces.is_dir():
        for p in sorted(faces.glob("*.enc")):
            did = p.stem
            home_lat, home_lon, home_n = _profile_for(did).home_coords()
            out.append(
                {
                    "driver_id": did,
                    "has_face": True,
                    "has_voice": (store / "voices" / f"{did}.enc").is_file(),
                    "home_lat": home_lat,
                    "home_lon": home_lon,
                    "home_set": home_n >= 1 and home_lat is not None,
                }
            )
    return out


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

    # Progressive unlock: more ladder rungs remain locked in this call.
    next_unlock: str | None = None
    if accept_mod is None:
        if "voice" in probed and "face" not in probed:
            next_unlock = "face"
        elif "face" in probed and "finger" not in probed:
            next_unlock = "finger"

    for mod in order:
        score = _mod_score(mod)
        idx = order.index(mod)
        if accept_idx is not None and idx > accept_idx:
            status, detail = "skipped", "early-stop · not probed"
        elif mod in probed:
            if accept_mod == mod:
                status = "accept"
                detail = f"≥ bar · {score:.3f}" if score is not None else "accepted"
            elif next_unlock and mod == last_probed:
                # Soft escalate — next modality still locked; do not mark reject.
                status = "escalate"
                detail = (
                    f"below bar · unlock {next_unlock}"
                    if score is not None
                    else f"no score · unlock {next_unlock}"
                )
            elif decided_reject and mod == last_probed:
                status = "reject"
                detail = f"exhausted · {score:.3f}" if score is not None else "exhausted"
            else:
                status = "escalate"
                detail = f"below bar · {score:.3f}" if score is not None else "no score"
        elif accept_mod is not None:
            status, detail = "skipped", "not needed"
        else:
            status, detail = "locked", "locked · not in this call"
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

    # Hard gates cancel progressive unlock (no soft escalate pause).
    if hard_gate:
        next_unlock = None
        for rung in ladder_stages:
            if rung["id"] == last_probed and rung["status"] == "escalate":
                score = rung.get("score")
                rung["status"] = "reject"
                rung["detail"] = (
                    f"exhausted · {score:.3f}" if score is not None else "exhausted"
                )

    decision = result.decision.value
    if next_unlock:
        ladder_status = "stepup"
        ladder_detail = (
            f"{' → '.join(probed) if probed else '—'} · escalate · "
            f"unlock {next_unlock}"
        )
        policy_status, policy_detail = "hold", f"paused · capture {next_unlock}"
        decision_status, decision_detail = "hold", f"ESCALATE · {next_unlock}"
        path_summary = (
            f"{' → '.join(m.title() for m in probed)} → escalate · "
            f"unlock {next_unlock}"
            if probed
            else f"escalate · unlock {next_unlock}"
        )
    else:
        ladder_status = (
            "block"
            if decision == "REJECT" and hard_gate is None
            else "accept"
            if decision == "ACCEPT"
            else "stepup"
            if decision == "STEP_UP_REQUIRED"
            else "done"
        )
        ladder_detail = (
            f"probed {' → '.join(probed) if probed else '—'}"
            + (f" · early-stop {accept_mod}" if accept_mod else "")
        )
        policy_status = (
            "accept"
            if decision == "ACCEPT"
            else "stepup"
            if decision == "STEP_UP_REQUIRED"
            else "block"
        )
        policy_detail = result.policy_rule or "—"
        decision_status = policy_status
        decision_detail = decision
        path_summary = hard_gate or (
            f"{' → '.join(m.title() for m in probed)} → {decision}"
            if probed
            else decision
        )

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
            "status": ladder_status,
            "detail": ladder_detail,
            "rungs": ladder_stages,
        },
        {
            "id": "policy",
            "label": "Policy",
            "status": policy_status,
            "detail": policy_detail,
        },
        {
            "id": "decision",
            "label": "Decision",
            "status": decision_status,
            "detail": decision_detail,
        },
    ]

    return {
        "stages": stages,
        "probed": probed,
        "accept_modality": accept_mod,
        "next_unlock": next_unlock,
        "pause_after": "ladder" if next_unlock else None,
        "hard_gate": hard_gate,
        "path_summary": path_summary,
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
    return render_dashboard(mode="manual")


@app.get("/manual", response_class=HTMLResponse)
def manual_page() -> str:
    return render_dashboard(mode="manual")


@app.get("/standalone", response_class=HTMLResponse)
def standalone_page() -> str:
    return render_dashboard(mode="standalone")


@app.get("/register", response_class=HTMLResponse)
def register_page() -> str:
    return render_register()


@app.get("/fleet", response_class=HTMLResponse)
def fleet_page() -> str:
    return render_fleet()


@app.get("/api/fleet/health")
def fleet_health() -> dict[str, Any]:
    """Local fleet-health snapshot — scores/rates only, no biometrics."""
    from driveauth import __version__
    from hardware.fleet_telemetry import build_telemetry_payload, summarize_audit_file

    store = _unified_store()
    audit = store / "audit" / "driveauth_events.jsonl"
    counts = summarize_audit_file(audit)
    payload = build_telemetry_payload(
        vehicle_id=os.getenv("DRIVEAUTH_VEHICLE_ID", "local"),
        firmware_version=os.getenv("DRIVEAUTH_FIRMWARE_VERSION", __version__),
        accept_count=counts["accept"],
        reject_count=counts["reject"],
        step_up_count=counts["step_up"],
        sensor_flags={
            "voice": True,
            "face": True,
            "finger": os.getenv("DRIVEAUTH_FINGERPRINT_AVAILABLE", "0") == "1",
            "gps": True,
        },
    )
    return payload


@app.get("/api/register/drivers")
def register_drivers_list() -> list[dict[str, Any]]:
    return list_registered_drivers(_data_root(), _register_store())


class RegisterDriverRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=32)


@app.get("/api/register/status")
def register_status(driver_id: str = "driver2") -> dict[str, Any]:
    try:
        return enrollment_status(_data_root(), _register_store(), driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _assert_register_writable(driver_id: str) -> None:
    """Block mutate APIs once voice+face templates are enrolled."""
    st = enrollment_status(_data_root(), _register_store(), driver_id)
    if st.get("locked"):
        raise HTTPException(
            status_code=403,
            detail=(
                f"{driver_id} is enrolled and locked — start a new Driver ID "
                "or continue a capturing (not enrolled) driver"
            ),
        )


@app.post("/api/register/init")
def register_init(req: RegisterDriverRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    try:
        root = ensure_driver_layout(_data_root(), driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "ok",
        "driver_id": driver_id,
        "data_dir": str(root),
        **enrollment_status(_data_root(), _register_store(), driver_id),
    }


@app.post("/api/register/face")
async def register_face(
    driver_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image upload")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="image too large")
    path = save_face_jpeg(_data_root(), driver_id, raw, split="enroll")
    return {
        "status": "ok",
        "path": str(path.relative_to(_data_root())),
        **enrollment_status(_data_root(), _register_store(), driver_id),
    }


@app.post("/api/register/voice")
async def register_voice(
    driver_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")
    if len(raw) > 8_000_000:
        raise HTTPException(status_code=400, detail="audio too large")
    try:
        path = save_voice_wav_bytes(_data_root(), driver_id, raw, split="enroll")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid WAV: {exc}") from exc
    return {
        "status": "ok",
        "path": str(path.relative_to(_data_root())),
        **enrollment_status(_data_root(), _register_store(), driver_id),
    }


class RegisterCompleteRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=32)
    # Explicit acknowledgment that biometric enrollment is consented.
    consent: bool = False
    consent_notes: str = ""


@app.post("/api/register/complete")
def register_complete(req: RegisterCompleteRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    if not req.consent:
        raise HTTPException(
            status_code=400,
            detail="consent required — set consent=true after informing the driver "
            "(BIPA/GDPR-class legal review still required for non-test drivers)",
        )
    profile = _profile_for(driver_id)
    home_lat, home_lon, _ = profile.home_coords()
    if home_lat is None or home_lon is None:
        raise HTTPException(
            status_code=400,
            detail="home location required — pin home on the map before enrolling",
        )
    data_dir = _data_root() / driver_id
    store = _register_store()
    record_consent(store, driver_id, notes=req.consent_notes or "dashboard /register")
    try:
        result = enroll_driver(store, data_dir, driver_id, require_minimums=True)
    except ConsentRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "home_lat": home_lat, "home_lon": home_lon, **result}


@app.post("/api/register/purge")
def register_purge(req: RegisterDriverRequest) -> dict[str, Any]:
    """Delete biometric templates + OOD + consent for a driver (Phase E)."""
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = purge_driver(
        _register_store(),
        driver_id,
        data_root=_data_root(),
        remove_sample_files=False,
    )
    return {"status": "ok", **result}


@app.post("/api/register/clear")
def register_clear(req: RegisterDriverRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    data_dir = _data_root() / driver_id
    for path in list_enroll_images(data_dir) + list_enroll_wavs(data_dir):
        path.unlink(missing_ok=True)
    return {
        "status": "ok",
        **enrollment_status(_data_root(), _register_store(), driver_id),
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
    path = (_data_root() / driver_id / "face" / "enroll" / safe).resolve()
    enroll_root = (_data_root() / driver_id / "face" / "enroll").resolve()
    if not path.is_relative_to(enroll_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/status")
def status() -> dict[str, Any]:
    auth = get_auth(use_mock=True)
    mature = auth._profile.is_mature()
    rigor = auth._fraud.effective_rigor(mature)
    home_lat, home_lon, home_n = auth._profile.home_coords()
    return {
        "store_dir": auth._store,
        "driver_id": auth.driver_id,
        "fraud_state": auth._fraud.effective_state(mature).value,
        "fraud_ladder": auth._fraud.state.value,
        "profile_mature": mature,
        "profile_maturity": auth._profile.maturity_reason(),
        "fraud_rigor": rigor,
        "enabled": auth._enabled,
        "use_mock": _want_mock(),
        "openrouter": openrouter_configured(),
        "google_maps": bool(google_maps_key()),
        "home_lat": home_lat,
        "home_lon": home_lon,
        "home_set": home_n >= 1 and home_lat is not None,
    }


class HomeRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=32)
    lat: float
    lon: float


@app.post("/api/register/home")
def register_home(req: HomeRequest) -> dict[str, Any]:
    try:
        driver_id = validate_driver_id(req.driver_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_register_writable(driver_id)
    if not (-90.0 <= req.lat <= 90.0 and -180.0 <= req.lon <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lon out of range")
    profile = _profile_for(driver_id)
    profile.set_home(req.lat, req.lon)
    lat, lon, n = profile.home_coords()
    return {
        "status": "ok",
        "driver_id": driver_id,
        "home_lat": lat,
        "home_lon": lon,
        "home_n": n,
    }


@app.get("/api/standalone/config")
def standalone_config() -> dict[str, Any]:
    return {
        "openrouter": openrouter_configured(),
        "google_maps_api_key": google_maps_key(),
        "default_driver": _default_driver(),
        "store_dir": str(_unified_store()),
        "use_mock": _want_mock(),
        "drivers": _list_enrolled_drivers(),
    }


@app.get("/api/standalone/drivers")
def standalone_drivers() -> list[dict[str, Any]]:
    return _list_enrolled_drivers()


class IntentRequest(BaseModel):
    transcript: str = ""
    amount: float = 0.0
    beneficiary: str = ""
    action: str = "pay"
    currency: str = "INR"
    synthesize_tts: bool = True
    use_llm: bool = True


@app.post("/api/standalone/intent")
def standalone_intent(req: IntentRequest) -> dict[str, Any]:
    prior = IntentSlots(
        amount=req.amount,
        beneficiary=req.beneficiary,
        action=req.action or "pay",
        currency=req.currency or "INR",
        is_payment=bool(req.amount > 0 or req.beneficiary),
    )
    result = process_transcript(
        req.transcript,
        prior=prior if (prior.amount or prior.beneficiary) else None,
        use_llm=req.use_llm and openrouter_configured(),
        synthesize_tts=req.synthesize_tts and openrouter_configured(),
    )
    return result.as_dict()


@app.post("/api/standalone/transcribe")
async def standalone_transcribe(
    file: UploadFile = File(...),
    amount: float = Form(0.0),
    beneficiary: str = Form(""),
    action: str = Form("pay"),
    currency: str = Form("INR"),
    synthesize_tts: bool = Form(True),
    use_llm: bool = Form(True),
) -> dict[str, Any]:
    if not openrouter_configured():
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY missing — fill secrets.env",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(raw) > 12_000_000:
        raise HTTPException(status_code=400, detail="audio too large")
    prior = IntentSlots(
        amount=amount,
        beneficiary=beneficiary,
        action=action or "pay",
        currency=currency or "INR",
        is_payment=bool(amount > 0 or beneficiary),
    )
    fmt = "wav"
    if file.filename and "." in file.filename:
        fmt = file.filename.rsplit(".", 1)[-1].lower()
    result = process_audio(
        raw,
        audio_format=fmt,
        prior=prior if (prior.amount or prior.beneficiary) else None,
        use_llm=use_llm,
        synthesize_tts=synthesize_tts,
    )
    return result.as_dict()


@app.post("/api/standalone/auth")
async def standalone_auth(
    driver_id: str = Form(None),
    amount: float = Form(...),
    beneficiary: str = Form(...),
    action: str = Form("pay"),
    currency: str = Form("INR"),
    beneficiary_known: bool = Form(True),
    is_guest: bool = Form(False),
    finger: float | None = Form(None),
    behavioral: float = Form(0.95),
    gps_lat: float | None = Form(None),
    gps_lon: float | None = Form(None),
    gps_accuracy_m: float = Form(50.0),
    speed_kmh: float = Form(0.0),
    ignition_on: bool = Form(True),
    is_tunnel: bool = Form(False),
    audio: UploadFile = File(...),
    face: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Live voice (+ optional face) auth; finger score stays manual when unlocked."""
    try:
        did = validate_driver_id(driver_id or _default_driver())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    wav = await audio.read()
    if not wav:
        raise HTTPException(status_code=400, detail="empty audio")
    try:
        audio_np = wav_bytes_to_float32(wav)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid WAV: {exc}") from exc

    face_bgr = None
    if face is not None:
        face_raw = await face.read()
        if face_raw:
            face_bgr = _decode_face_jpeg(face_raw)

    try:
        auth = get_auth(did, use_mock=False, mature=True)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"failed to load live matchers for {did}: {exc}",
        ) from exc

    # Progressive unlock: finger only when the client sends a score.
    _apply_finger_manual(auth, finger)
    auth._engine._m.behavioral = MockBehavioralMonitor(score=behavioral)

    face_matcher = getattr(auth._engine._m, "face", None)
    if face_bgr is not None and face_matcher is not None and hasattr(face_matcher, "inject_bgr"):
        face_matcher.inject_bgr(face_bgr)

    # GPS only — let ProfileStore compute dist_from_home / trusted zone.
    ctx: dict[str, Any] = {
        "speed_kmh": speed_kmh,
        "ignition_on": ignition_on,
        "is_tunnel": is_tunnel,
        "gps_accuracy_m": gps_accuracy_m,
    }
    if gps_lat is not None and gps_lon is not None:
        ctx["gps_lat"] = gps_lat
        ctx["gps_lon"] = gps_lon
        # Leave dist/zone at RiskContext defaults so apply_to_context fills them.
        ctx["dist_from_home_km"] = 0.0
        ctx["in_trusted_zone"] = True
    auth.update_vehicle_context(**ctx)
    auth.update_behavioral(
        {"vehicle_speed_kmh": speed_kmh, "ignition_on": float(ignition_on)}
    )

    result = auth.authenticate(
        audio_np=audio_np,
        amount=float(amount),
        beneficiary=beneficiary,
        action=action,
        currency=currency,
        channel="standalone",
        beneficiary_known=beneficiary_known,
        is_guest=is_guest,
        event="standalone_auth",
        # Face locked until the client supplies a JPEG (after voice escalates).
        face_expected=face_bgr is not None,
    )
    payload = _result_payload(result)
    if gps_lat is not None and gps_lon is not None:
        dist, zone = auth._profile.location_context(gps_lat, gps_lon)
        payload["dist_from_home_km"] = dist
        payload["in_trusted_zone"] = zone
        payload["gps_lat"] = gps_lat
        payload["gps_lon"] = gps_lon
    return payload


@app.post("/api/context")
def update_context(ctx: VehicleContext) -> dict[str, Any]:
    auth = get_auth(use_mock=True)
    data = {k: v for k, v in ctx.model_dump().items() if v is not None}
    # When GPS is provided without an explicit distance override, keep
    # dist_from_home_km=0 / in_trusted_zone=True so ProfileStore fills them.
    if ctx.gps_lat is not None and ctx.gps_lon is not None:
        data.setdefault("dist_from_home_km", 0.0)
        data.setdefault("in_trusted_zone", True)
    auth.update_vehicle_context(**data)
    auth.update_behavioral(
        {"vehicle_speed_kmh": ctx.speed_kmh, "ignition_on": float(ctx.ignition_on)}
    )
    out: dict[str, Any] = {"status": "ok"}
    if ctx.gps_lat is not None and ctx.gps_lon is not None:
        dist, zone = auth._profile.location_context(ctx.gps_lat, ctx.gps_lon)
        out["dist_from_home_km"] = dist
        out["in_trusted_zone"] = zone
    return out


@app.post("/api/authenticate")
def authenticate(req: AuthenticateRequest) -> dict[str, Any]:
    auth = get_auth(use_mock=True)
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
    auth = get_auth(use_mock=True)
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
    auth = get_auth(use_mock=True)
    state = auth._fraud.record_soft_flag(reason)
    return {"fraud_state": state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/fraud/clean")
def fraud_clean() -> dict[str, Any]:
    auth = get_auth(use_mock=True)
    state = auth._fraud.record_clean()
    return {"fraud_state": state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/fraud/reset")
def fraud_reset() -> dict[str, Any]:
    auth = get_auth(use_mock=True)
    auth._fraud.reset()
    return {"fraud_state": auth._fraud.state.value, "rigor": auth._fraud.rigor()}


@app.post("/api/reset")
def reset_session(mature: bool = True) -> dict[str, Any]:
    auth = reset_auth(mature=mature, use_mock=True)
    return {
        "status": "ok",
        "store_dir": auth._store,
        "profile_mature": auth._profile.is_mature(),
        "fraud_state": auth._fraud.effective_state(auth._profile.is_mature()).value,
    }


@app.post("/api/profile/mature")
def profile_mature() -> dict[str, Any]:
    auth = get_auth(use_mock=True)
    auth._profile.seed_mature()
    mature = True
    return {
        "profile_mature": mature,
        "profile_maturity": auth._profile.maturity_reason(),
        "fraud_state": auth._fraud.effective_state(mature).value,
    }


@app.post("/api/profile/bootstrap")
def profile_bootstrap() -> dict[str, Any]:
    auth = get_auth(use_mock=True)
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
