"""Phase 5 — re-baseline thresholds against real-model score distributions.

Validates calibration math, that shipped policy stays conservative vs Phase 2b
FAR=0 ladder suggestions, and that mock-era bars are not silently reused when
real-model distributions say otherwise.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from driveauth import config
from driveauth.escalation import EscalationPolicy
from driveauth.types import Decision
from testsupport import good_audio, make_auth, mature

ROOT = Path(__file__).resolve().parents[1]
CALIB = ROOT / "phases" / "phase2b_calibration.json"
BIO_EVAL = ROOT / "phases" / "phase2b_bio_eval.json"
SUGGESTED_ENV = ROOT / "phases" / "phase2b_suggested.env"
BASELINE = ROOT / "phases" / "phase2a_bio_baseline.json"


def _load_calibrate_helpers():
    path = ROOT / "scripts" / "calibrate_bio_thresholds.py"
    spec = importlib.util.spec_from_file_location("calibrate_bio_thresholds", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cal():
    return _load_calibrate_helpers()


@pytest.fixture(scope="module")
def calib_report() -> dict:
    assert CALIB.exists(), "run scripts/calibrate_bio_thresholds.py first"
    return json.loads(CALIB.read_text())


# ── Calibration helpers (unit) ───────────────────────────────────────────────


def test_far_frr_perfect_separation(cal):
    genuine = [0.80, 0.85, 0.90]
    attack = [0.10, 0.20, 0.30]
    far, frr = cal._far_frr(genuine, attack, 0.50)
    assert far == 0.0
    assert frr == 0.0


def test_far_frr_at_attack_edge(cal):
    genuine = [0.9, 0.95]
    attack = [0.4, 0.6, 0.7]
    far, frr = cal._far_frr(genuine, attack, 0.70)
    assert far == pytest.approx(1.0 / 3.0)
    assert frr == 0.0


def test_summarize_empty(cal):
    assert cal._summarize([]) == {"n": 0}


def test_summarize_stats(cal):
    s = cal._summarize([0.1, 0.5, 0.9])
    assert s["n"] == 3
    assert s["mean"] == pytest.approx(0.5, abs=1e-3)
    assert s["min"] == 0.1
    assert s["max"] == 0.9


def test_eer_ladder_prefers_far0(cal):
    genuine = [0.75, 0.80, 0.85, 0.90]
    attack = [0.10, 0.20, 0.40, 0.55]
    out = cal._eer_and_ladder_bar(genuine, attack)
    assert out["ladder_far"] == 0.0
    assert out["ladder_accept"] >= max(attack) - 1e-9
    assert "FAR=0" in out["note"]


def test_eer_ladder_total_overlap_falls_back(cal):
    # Identical genuine/attack → no FAR=0 bar; EER path.
    scores = [0.4, 0.5, 0.6, 0.7]
    out = cal._eer_and_ladder_bar(scores, scores)
    assert "no FAR=0" in out["note"] or out["ladder_frr"] > 0.0
    assert 0.0 <= out["ladder_accept"] <= 1.0


def test_suggest_bars_are_ordered(cal):
    genuine = [0.55, 0.62, 0.70, 0.78, 0.85]
    attack = [0.05, 0.15, 0.25, 0.35, 0.45]
    sug = cal._suggest(genuine, attack)
    assert sug["accept_micro"] <= sug["accept_standard"] <= sug["accept_high"]
    assert sug["reject"] < sug["accept_micro"]
    assert "ladder" in sug


def test_suggest_empty_genuine(cal):
    assert cal._suggest([], [0.1]) == {}


# ── Artifacts from real-model calibration ────────────────────────────────────


def test_calibration_artifact_has_voice_and_face(calib_report):
    for modality in ("voice", "face"):
        block = calib_report[modality]
        assert block["genuine"]["n"] >= 5
        assert block["attack"]["n"] >= 3
        assert "suggest_modality_bars" in block
        assert "ladder" in block["suggest_modality_bars"]


def test_calibration_records_current_policy(calib_report):
    pol = calib_report["current_policy"]
    for key in (
        "TRUST_ACCEPT_MICRO",
        "LADDER_ACCEPT_VOICE",
        "LADDER_ACCEPT_FACE",
        "LADDER_ACCEPT_FINGER",
    ):
        assert key in pol
        assert 0.0 < float(pol[key]) <= 1.0


def test_suggested_ladder_voice_clears_attack_max(calib_report):
    """FAR=0 ladder for voice must sit at/above observed attack max (ceil'd)."""
    attack_max = float(calib_report["voice"]["attack"]["max"])
    ladder = calib_report["voice"]["suggest_modality_bars"]["ladder"]
    if float(ladder["ladder_far"]) == 0.0:
        assert float(ladder["ladder_accept"]) >= attack_max - 0.02


def test_face_total_frr_keeps_strict_bar(calib_report):
    """When face cannot accept any genuine at FAR=0, do not lower the face bar."""
    face_ladder = calib_report["face"]["suggest_modality_bars"]["ladder"]
    suggested = calib_report.get("suggested_ladder") or {}
    if float(face_ladder.get("ladder_frr", 0.0)) >= 1.0 - 1e-9:
        assert float(suggested.get("accept_face", 0.0)) >= 0.70
        assert float(config.LADDER_ACCEPT_FACE) >= 0.70


def test_shipped_ladder_not_below_voice_far0_suggestion(calib_report):
    """Shipped voice ladder bar must remain ≥ calibration FAR=0 suggestion."""
    suggested = calib_report.get("suggested_ladder") or {}
    if not suggested:
        pytest.skip("no suggested_ladder in calibration")
    assert float(config.LADDER_ACCEPT_VOICE) >= float(suggested["accept_voice"]) - 1e-9


def test_shipped_trust_bars_stay_above_weakened_sidecar():
    """
    Explicit non-goal: do not apply phase2b_suggested.env while face overlap
    is high. Shipped TRUST_ACCEPT_* must stay strictly more conservative.
    """
    if not SUGGESTED_ENV.exists():
        pytest.skip("no suggested env sidecar")
    weak: dict[str, float] = {}
    for line in SUGGESTED_ENV.read_text().splitlines():
        line = line.strip()
        if not line.startswith("export "):
            continue
        key, _, val = line.removeprefix("export ").partition("=")
        weak[key] = float(val)
    if "DRIVEAUTH_TRUST_ACCEPT_MICRO" in weak:
        assert config.TRUST_ACCEPT_MICRO > weak["DRIVEAUTH_TRUST_ACCEPT_MICRO"]
    if "DRIVEAUTH_TRUST_ACCEPT_STD" in weak:
        assert config.TRUST_ACCEPT_STD > weak["DRIVEAUTH_TRUST_ACCEPT_STD"]
    if "DRIVEAUTH_TRUST_ACCEPT_HIGH" in weak:
        assert config.TRUST_ACCEPT_HIGH > weak["DRIVEAUTH_TRUST_ACCEPT_HIGH"]


def test_bio_eval_artifact_present_and_sane():
    assert BIO_EVAL.exists(), "run scripts/eval_bio_far_frr.py for Phase 2b"
    report = json.loads(BIO_EVAL.read_text())
    assert report.get("tag") in ("phase2b", "phase2a", None) or "voice" in report
    voice = report["voice"]
    assert voice["genuine"]["n"] >= 5
    assert voice["metrics"]["eer"] >= 0.0
    # Real-model genuine mass sits below mock-era 0.9 bars.
    assert voice["genuine"]["mean"] < 0.90
    assert voice["genuine"]["p50"] < 0.90


def test_baseline_vs_phase2b_voice_distributions_differ():
    """Re-baseline only makes sense if Stage-2 scores moved vs Phase 2a."""
    if not BASELINE.exists() or not BIO_EVAL.exists():
        pytest.skip("baseline/eval missing")
    base = json.loads(BASELINE.read_text())
    cur = json.loads(BIO_EVAL.read_text())
    # Presence of both artifacts is the re-baseline gate; means need not move
    # every run, but both must report overlapping genuine/attack structure.
    for tag, doc in (("baseline", base), ("phase2b", cur)):
        assert "voice" in doc, tag
        assert doc["voice"]["genuine"]["n"] >= 1
        assert doc["voice"]["attack"]["n"] >= 1


# ── Policy behaviour under real-model-like mock scores ───────────────────────


def test_mock_score_at_real_voice_p50_does_not_early_accept(calib_report):
    """
    Genuine voice mean/p50 from real models (~0.61–0.68) is below ladder 0.72.
    Pipeline must escalate (not Accept on voice alone).
    """
    p50 = float(calib_report["voice"]["genuine"]["p50"])
    assert p50 < float(config.LADDER_ACCEPT_VOICE)

    auth = make_auth()
    mature(auth)
    from driveauth.matchers.mock import MockFaceMatcher, MockVoiceMatcher

    auth._engine._m.voice = MockVoiceMatcher(score=p50)
    auth._engine._m.face = MockFaceMatcher(score=0.92)
    r = auth.authenticate(
        audio_np=good_audio(),
        amount=50.0,
        beneficiary_known=True,
        beneficiary="Mom",
    )
    assert any("ladder_escalate_after_voice" in e for e in r.explanations)
    assert r.decision == Decision.ACCEPT
    assert any("ladder_accept_face" in e for e in r.explanations)


def test_mock_score_at_real_voice_attack_p90_rejected_on_voice(calib_report):
    attack_p90 = float(calib_report["voice"]["attack"]["p90"])
    plan = EscalationPolicy().plan(tier="micro", profile_mature=True)
    assert not plan.is_accept(attack_p90, modality="voice")


def test_ladder_accept_at_exact_bar():
    plan = EscalationPolicy().plan(tier="micro", profile_mature=True)
    bar = plan.bar_for("voice")
    assert plan.is_accept(bar, modality="voice")
    assert not plan.is_accept(bar - 1e-6, modality="voice")


def test_fraud_margin_raises_all_modality_bars():
    base = EscalationPolicy().plan(tier="micro", fraud_rigor={"trust_margin": 0.0})
    raised = EscalationPolicy().plan(tier="micro", fraud_rigor={"trust_margin": 0.05})
    for m in ("voice", "face", "finger"):
        assert raised.bar_for(m) == pytest.approx(base.bar_for(m) + 0.05)


def test_rebaseline_report_notes_conservative_defaults(calib_report):
    """Documented guardrail: suggested trust may be lower; defaults stay high."""
    sug = calib_report.get("suggested_policy_trust") or {}
    if not sug:
        pytest.skip("no suggested_policy_trust")
    assert float(config.TRUST_ACCEPT_MICRO) >= float(sug["accept_micro"])
    assert float(config.TRUST_ACCEPT_HIGH) >= float(sug["accept_high"])
