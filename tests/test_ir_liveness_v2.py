"""Phase 8 — multi-signal IR liveness (reflectance + blink + moiré).

Liveness v2 is a stronger heuristic ensemble; still not independently
certified anti-spoofing. Certification requires third-party PAD testing
against ISO/IEC 30107-3, which is out of scope.
"""

from __future__ import annotations

import numpy as np
import pytest

from hardware.ir_liveness import (
    IRLivenessChecker,
    combine_liveness_scores,
    heuristic_live_proba,
    extract_ir_reflectance_features,
    score_blink_motion,
    score_moire,
)


# ── synthetic samples ───────────────────────────────────────────────────────


def _live_skin(size: int = 112, seed: int = 0) -> np.ndarray:
    """Mid-tone textured IR face crop (reflectance-live)."""
    rng = np.random.default_rng(seed)
    base = rng.normal(110, 25, (size, size)).astype(np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    base += 8.0 * np.sin(xx / 3.0) * np.cos(yy / 4.0)
    return np.clip(base, 0, 255)


def _spoof_flat_screen(size: int = 112) -> np.ndarray:
    """Flat bright plate — IR reflectance spoof."""
    return np.full((size, size), 248.0, dtype=np.float32)


def _blink_live_burst(size: int = 112) -> list[np.ndarray]:
    """Three frames with an eye-band darkening then recovery (blink)."""
    open_eye = _live_skin(size, seed=1)
    mid = open_eye.copy()
    y0, y1 = size // 4, size // 2
    mid[y0:y1, :] = np.clip(mid[y0:y1, :] - 35.0, 0, 255)
    # Tiny global micro-motion between frames.
    closed = open_eye.copy()
    closed = np.roll(closed, 1, axis=0)
    return [open_eye, mid, closed]


def _blink_spoof_static(size: int = 112) -> list[np.ndarray]:
    """Identical frames — frozen print / screen (no blink)."""
    frame = _live_skin(size, seed=2)
    return [frame.copy(), frame.copy(), frame.copy()]


def _moire_screen_replay(size: int = 112) -> np.ndarray:
    """Skin-like base + hard LCD pixel lattice (screen replay)."""
    base = _live_skin(size, seed=3)
    yy, xx = np.mgrid[0:size, 0:size]
    pitch = 4
    grid = 80.0 * (
        ((xx % pitch) < 1).astype(np.float32) + ((yy % pitch) < 1).astype(np.float32)
    )
    return np.clip(base * 0.4 + 100.0 + grid, 0, 255).astype(np.float32)


def _moire_live_skin(size: int = 112) -> np.ndarray:
    """Natural texture without a regular lattice."""
    return _live_skin(size, seed=4)


# ── per-signal unit tests ───────────────────────────────────────────────────


def test_reflectance_separates_live_and_spoof():
    live_f = extract_ir_reflectance_features(_live_skin())
    spoof_f = extract_ir_reflectance_features(_spoof_flat_screen())
    live_s = heuristic_live_proba(live_f)
    spoof_s = heuristic_live_proba(spoof_f)
    assert live_s >= 0.55
    assert spoof_s < 0.55
    assert live_s - spoof_s >= 0.2


def test_blink_motion_detects_blink_vs_static():
    live_s = score_blink_motion(_blink_live_burst())
    spoof_s = score_blink_motion(_blink_spoof_static())
    assert live_s >= 0.55
    assert spoof_s < 0.45
    assert live_s - spoof_s >= 0.2


def test_blink_fail_closed_on_single_frame():
    assert score_blink_motion([_live_skin()]) == 0.0
    assert score_blink_motion([]) == 0.0


def test_moire_flags_screen_grid():
    live_s = score_moire(_moire_live_skin())
    spoof_s = score_moire(_moire_screen_replay())
    assert live_s > spoof_s
    assert spoof_s < 0.55
    assert live_s - spoof_s >= 0.15


# ── ensemble / checker ──────────────────────────────────────────────────────


def test_default_checker_is_reflectance_only():
    """ensemble=False must match Phase-3 behaviour exactly."""
    checker = IRLivenessChecker(threshold=0.55, ensemble=False)
    assert checker.ensemble is False
    live = checker.check(_live_skin())
    spoof = checker.check(_spoof_flat_screen())
    assert live.live is True
    assert spoof.live is False
    assert live.signal_scores == {"reflectance": live.score}
    assert "blink" not in live.signal_scores


def test_ensemble_combined_score_live_burst():
    checker = IRLivenessChecker(threshold=0.55, ensemble=True)
    frames = _blink_live_burst()
    r = checker.check_sequence(frames)
    assert r.live is True
    assert set(r.signal_scores) == {"reflectance", "blink", "moire"}
    assert r.score == pytest.approx(
        combine_liveness_scores(r.signal_scores), abs=1e-6
    )


def test_ensemble_rejects_static_screen_replay():
    """Screen lattice + no blink should fail the ensemble even if reflectance is middling."""
    checker = IRLivenessChecker(threshold=0.55, ensemble=True)
    screen = _moire_screen_replay()
    frames = [screen.copy(), screen.copy(), screen.copy()]
    r = checker.check_sequence(frames)
    assert r.live is False
    assert r.signal_scores["blink"] < 0.45
    assert r.signal_scores["moire"] < 0.55


def test_ensemble_fail_closed_missing_crop():
    checker = IRLivenessChecker(ensemble=True)
    r = checker.check(None)
    assert r.live is False
    assert r.reason == "missing_crop"


def test_ensemble_single_frame_blink_is_zero():
    """Opted-in ensemble without a burst: blink contributes 0 (fail-closed)."""
    checker = IRLivenessChecker(threshold=0.55, ensemble=True)
    r = checker.check(_live_skin())
    assert r.signal_scores["blink"] == 0.0


def test_combine_renormalizes_over_present_weights():
    scores = {"reflectance": 1.0, "moire": 0.0}
    # blink absent → reflectance 0.45 + moire 0.25 = 0.70 mass
    combined = combine_liveness_scores(scores)
    assert combined == pytest.approx(0.45 / 0.70, abs=1e-6)


def test_extension_point_classifier_still_works():
    checker = IRLivenessChecker(classifier=lambda feats: 0.99, ensemble=False)
    assert checker.check(_spoof_flat_screen()).live is True
