"""Sprint 1 security tests — timing pad + OOD-refresh gate (drift defence)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import numpy as np

from driveauth import config
from driveauth import DriveAuth
from driveauth.matchers.mock import MockFaceMatcher, MockFingerMatcher, MockVoiceMatcher
from driveauth.matchers.score_provider import ManualScores, apply_manual_scores
from driveauth.ood_detector import OODDetector
from driveauth.profile_store import ProfileStore
from testsupport import good_audio, mature


def _align_error_ms(elapsed_s: float, quantum_ms: float) -> float:
    """Distance from elapsed time to the nearest multiple of the quantum (ms)."""
    ms = elapsed_s * 1000.0
    rem = ms % quantum_ms
    return min(rem, quantum_ms - rem)


def test_escalation_constant_time_aligns_accept_and_stepup(monkeypatch):
    """
    With ESCALATION_CONSTANT_TIME_MS > 0, wall times for early-stop ACCEPT and
    multi-probe STEP_UP both land on the quantum grid (side-channel mitigation).
    """
    quantum_ms = 50.0
    monkeypatch.setattr(config, "ESCALATION_CONSTANT_TIME_MS", quantum_ms)

    store = tempfile.mkdtemp(prefix="driveauth_timing_")
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    auth._engine._m.fingerprint_available = True

    def timed(scores: ManualScores) -> float:
        apply_manual_scores(auth, scores)
        t0 = time.perf_counter()
        auth.authenticate(
            audio_np=good_audio(),
            amount=50.0,
            beneficiary_known=True,
            beneficiary="Mom",
            audit=False,
        )
        return time.perf_counter() - t0

    # Cold start / first JIT-ish hit can miss the grid — warm once.
    timed(ManualScores(voice=0.95, face=0.9, finger=0.9, behavioral=0.95))

    accept_times = [
        timed(ManualScores(voice=0.95, face=0.9, finger=0.9, behavioral=0.95))
        for _ in range(10)
    ]
    step_times = [
        timed(ManualScores(voice=0.45, face=0.45, finger=0.2, behavioral=0.95))
        for _ in range(10)
    ]

    for label, times in (("accept", accept_times), ("stepup", step_times)):
        errs = sorted(_align_error_ms(t, quantum_ms) for t in times)
        # Sleep scheduling is soft RT; require p90 within slack, not every sample
        p90 = errs[int(0.9 * (len(errs) - 1))]
        assert p90 < 12.0, f"{label} p90 alignment={p90} errs={errs}"

    mean_a = float(np.mean(accept_times))
    mean_s = float(np.mean(step_times))
    assert abs(mean_a - mean_s) < (1.5 * quantum_ms / 1000.0) + 0.03


def test_escalation_constant_time_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(config, "ESCALATION_CONSTANT_TIME_MS", 0.0)
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    t0 = time.perf_counter()
    auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    # Mock path is sub-10ms; without pad must stay well under a 40ms quantum
    assert (time.perf_counter() - t0) < 0.035


def test_ood_drift_refresh_blocked_without_strong_auth():
    """
    Drift attack: attacker tries to rewrite OOD baselines after weak/no auth.
    Gate must refuse; version must not bump when caller respects can_refresh_ood.
    """
    store = tempfile.mkdtemp(prefix="driveauth_ood_drift_")
    profile = ProfileStore(Path(store) / "profiles" / "driver1.json", "driver1")
    assert profile.ood_version == 0

    # Simulate attacker without strong auth
    assert profile.can_refresh_ood(strong_auth_passed=False) is False
    # Correct caller: do NOT bump / reseed when gated
    v_before = profile.ood_version

    # Even if attacker writes files on disk (out of band), the gate documents
    # that application code must not call bump_ood_version / seed overwrite.
    # Strong auth is the only allowed refresh path:
    assert profile.can_refresh_ood(strong_auth_passed=True) is True
    v_after = profile.bump_ood_version()
    assert v_after == v_before + 1
    assert profile.ood_version == v_after
    assert profile._p.ood_last_refresh_at > 0


def test_ood_drift_attack_cannot_legally_poison_via_api_gate():
    """
    End-to-end stance: DriveAuth profile gate stays closed after a normal
    ACCEPT (biometrics alone ≠ independently-strong OTP+finger style auth).
    """
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    r = auth.authenticate(
        audio_np=good_audio(), amount=50.0, beneficiary_known=True, beneficiary="Mom"
    )
    assert r.decision.value == "ACCEPT"
    # Soft biometric ACCEPT must not unlock OOD baseline refresh
    assert auth._profile.can_refresh_ood(strong_auth_passed=False) is False
    v0 = auth._profile.ood_version

    # Attacker-style silent reseed of zeros would change live stats if allowed —
    # policy is callers check the gate first (documented in ProfileStore).
    if auth._profile.can_refresh_ood(strong_auth_passed=False):
        OODDetector.seed_baselines(store, auth.driver_id, face_dim=8)
        auth._profile.bump_ood_version()
    assert auth._profile.ood_version == v0


def test_ood_refresh_with_strong_auth_allows_version_bump_and_reseed():
    store = tempfile.mkdtemp()
    auth = DriveAuth.load(store_dir=store, use_mock_matchers=True)
    mature(auth)
    v0 = auth._profile.ood_version
    assert auth._profile.can_refresh_ood(strong_auth_passed=True)
    OODDetector.seed_baselines(
        store,
        auth.driver_id,
        voice_dim=192,
        face_dim=512,
        finger_dim=64,
    )
    v1 = auth._profile.bump_ood_version()
    assert v1 == v0 + 1
    stats = Path(store) / "ood_stats" / f"face_{auth.driver_id}.npz"
    assert stats.exists()
