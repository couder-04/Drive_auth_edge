"""Phase 6 / Sprint 6 — benchmark artifact + offline rebuild guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PHASES = ROOT / "phases"
SCRIPT = ROOT / "scripts" / "phase6_benchmark.py"
REPORT = PHASES / "phase6_sprint6.json"
MD = PHASES / "phase6.md"


REQUIRED_TOP = {
    "biometrics",
    "pad",
    "risk",
    "latency",
    "intent",
    "comparisons",
    "ablations",
    "exit",
}

REQUIRED_SYSTEMS = {
    "otp_only",
    "voice_only",
    "face_only",
    "static_mfa_voice_and_face",
    "staged_voice_face",
    "staged_full_proxy",
}


@pytest.mark.skipif(not REPORT.is_file(), reason="phase6_sprint6.json missing — run script")
def test_sprint6_json_has_required_sections():
    report = json.loads(REPORT.read_text())
    assert report.get("sprint") == 6
    missing = REQUIRED_TOP - set(report)
    assert not missing, missing
    assert "Sprint 6" in report["exit"] or "ablations" in report["exit"].lower()


@pytest.mark.skipif(not REPORT.is_file(), reason="phase6_sprint6.json missing")
def test_biometric_eer_and_roc_present():
    report = json.loads(REPORT.read_text())
    for mod in ("voice", "face"):
        block = report["biometrics"][mod]
        m = block["metrics"]
        assert 0.0 <= float(m["eer"]) <= 1.0
        assert "eer_far" in m and "eer_frr" in m
        assert block.get("roc_auc") is not None
        assert len(block.get("roc") or []) >= 5


@pytest.mark.skipif(not REPORT.is_file(), reason="phase6_sprint6.json missing")
def test_pad_and_risk_metrics():
    report = json.loads(REPORT.read_text())
    pad = report["pad"]
    assert pad.get("apcer") is not None
    assert pad.get("bpcer") is not None
    risk = report["risk"]
    assert float(risk["val_auc"]) > 0.9
    # Live run fills P/R/F1; offline may leave None.
    if risk.get("precision") is not None:
        assert 0.0 <= float(risk["precision"]) <= 1.0
        assert 0.0 <= float(risk["f1"]) <= 1.0


@pytest.mark.skipif(not REPORT.is_file(), reason="phase6_sprint6.json missing")
def test_system_comparison_baselines():
    report = json.loads(REPORT.read_text())
    systems = report["comparisons"]["systems"]
    missing = REQUIRED_SYSTEMS - set(systems)
    assert not missing, missing
    # OTP never bio-accepts.
    assert systems["otp_only"]["genuine_accept_rate"] == 0.0
    assert systems["otp_only"].get("far_with_secure_otp", 0.0) == 0.0
    # Staged vs static present with FAR/FRR.
    for key in ("staged_voice_face", "static_mfa_voice_and_face", "voice_only"):
        assert "far" in systems[key] and "frr" in systems[key]


@pytest.mark.skipif(not REPORT.is_file(), reason="phase6_sprint6.json missing")
def test_ablations_filled():
    report = json.loads(REPORT.read_text())
    abl = report["ablations"]
    sweep = abl["ladder_voice_bar_sweep"]
    assert len(sweep) >= 5
    assert sweep[0]["voice_bar"] < sweep[-1]["voice_bar"]
    es = abl["early_stop_vs_security_floor"]
    assert "at_shipping_bars" in es or "early_stop_staged" in es
    assert abl.get("stage2_vs_raw_2a") is not None


@pytest.mark.skipif(not MD.is_file(), reason="phase6.md missing")
def test_phase6_md_has_sprint_table():
    text = MD.read_text()
    assert "Sprint 6 summary table" in text
    assert "System comparison" in text
    assert "Ablations" in text
    assert "EER" in text
    assert "APCER" in text


def test_offline_rebuild_preserves_exit(tmp_path):
    """Offline mode must rewrite md/json without live matchers when scores cached."""
    if not REPORT.is_file():
        pytest.skip("no prior live dump")
    report = json.loads(REPORT.read_text())
    if not (report.get("biometrics") or {}).get("voice_scores"):
        pytest.skip("cached score lists missing — rerun live benchmark")

    import subprocess
    import sys

    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    # Seed out_json with prior scores so offline can read them via --out-json path…
    # Script reads previous from --out-json; copy first.
    out_json.write_text(REPORT.read_text())
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--offline",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    rebuilt = json.loads(out_json.read_text())
    assert rebuilt["sprint"] == 6
    assert "staged_voice_face" in rebuilt["comparisons"]["systems"]
    assert out_md.is_file() and "Sprint 6" in out_md.read_text()
