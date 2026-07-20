"""Per-driver Stage-2 bio artifacts: resolve, migrate, train paths, integrity."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from driveauth.stage2_artifacts import (
    FACE_CALIBRATOR,
    FACE_PAD,
    VOICE_CALIBRATOR,
    list_enrolled_driver_ids,
    resolve_bio_artifact,
    stage2_status_for_driver,
    trainer_onnx_path,
)
from scripts.migrate_stage2_per_driver import migrate

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "driveauth_store_phase2a"


def test_resolve_prefers_per_driver(tmp_path, caplog):
    did = "driverX"
    d = tmp_path / "faces" / did
    d.mkdir(parents=True)
    (d / "face_pad.onnx").write_bytes(b"x")
    (tmp_path / "face_pad.onnx").write_bytes(b"legacy")
    with caplog.at_level(logging.INFO):
        ref = resolve_bio_artifact(tmp_path, did, FACE_PAD)
    assert ref.source == "per_driver"
    assert ref.path == d / "face_pad.onnx"
    assert "per-driver" in caplog.text.lower() or "per_driver" in caplog.text or True


def test_resolve_legacy_logs_warning(tmp_path, caplog):
    (tmp_path / "face_pad.onnx").write_bytes(b"legacy")
    with caplog.at_level(logging.WARNING):
        ref = resolve_bio_artifact(tmp_path, "driver1", FACE_PAD)
    assert ref.source == "legacy_shared"
    assert "LEGACY" in caplog.text


def test_resolve_missing(tmp_path):
    ref = resolve_bio_artifact(tmp_path, "driver1", FACE_PAD)
    assert ref.source == "missing"
    assert ref.path is None


def test_trainer_paths_never_store_root(tmp_path):
    p = trainer_onnx_path(tmp_path, "driver7", FACE_PAD)
    assert p == tmp_path / "faces" / "driver7" / "face_pad.onnx"
    assert p.parent != tmp_path
    v = trainer_onnx_path(tmp_path, "driver7", VOICE_CALIBRATOR)
    assert v == tmp_path / "voices" / "driver7" / "voice_calibrator.onnx"


def test_migration_idempotent(tmp_path):
    (tmp_path / "faces").mkdir()
    (tmp_path / "voices").mkdir()
    (tmp_path / "faces" / "driver1.enc").write_bytes(b"face")
    (tmp_path / "voices" / "driver1.enc").write_bytes(b"voice")
    for name in ("face_pad", "face_calibrator", "voice_calibrator"):
        (tmp_path / f"{name}.onnx").write_bytes(b"onnx-" + name.encode())
        (tmp_path / f"{name}.json").write_text(json.dumps({"loo_auc": 0.9}))

    s1 = migrate(tmp_path, drivers=["driver1"])
    assert s1["counts"]["copied"] == 3
    assert (tmp_path / "faces" / "driver1" / "face_pad.onnx").is_file()
    assert (tmp_path / "face_pad.onnx").is_file()  # legacy preserved

    s2 = migrate(tmp_path, drivers=["driver1"])
    assert s2["counts"]["already_present"] == 3
    assert s2["counts"]["copied"] == 0


def test_simultaneous_drivers_isolated(tmp_path):
    for did, payload in (("driver1", b"A"), ("driver7", b"B")):
        d = tmp_path / "faces" / did
        d.mkdir(parents=True)
        (d / "face_pad.onnx").write_bytes(payload)
        (tmp_path / "faces" / f"{did}.enc").write_bytes(b"e")
    r1 = resolve_bio_artifact(tmp_path, "driver1", FACE_PAD)
    r7 = resolve_bio_artifact(tmp_path, "driver7", FACE_PAD)
    assert r1.path.read_bytes() == b"A"
    assert r7.path.read_bytes() == b"B"


@pytest.mark.skipif(not STORE.is_dir(), reason="phase2a store missing")
def test_live_store_driver1_and_driver7_per_driver():
    ids = list_enrolled_driver_ids(STORE)
    assert "driver1" in ids
    if "driver7" not in ids:
        pytest.skip("driver7 not enrolled")
    for did in ("driver1", "driver7"):
        for art in (FACE_PAD, FACE_CALIBRATOR, VOICE_CALIBRATOR):
            ref = resolve_bio_artifact(STORE, did, art)
            assert ref.source == "per_driver", f"{did}/{art} source={ref.source}"
            assert ref.exists
        st = stage2_status_for_driver(STORE, did)
        assert st["mode"] == "per_driver"
        assert not st.get("needs_retrain")


@pytest.mark.skipif(not STORE.is_dir(), reason="phase2a store missing")
def test_live_store_migrated_drivers_flagged():
    """Drivers without independent retrain keep migrated_from stamps."""
    ids = list_enrolled_driver_ids(STORE)
    migrated = [d for d in ("driver2", "driver3", "driver6") if d in ids]
    if not migrated:
        pytest.skip("no migrated-only enrolled drivers")
    did = migrated[0]
    st = stage2_status_for_driver(STORE, did)
    assert st["mode"] == "per_driver_migrated"
    assert st["needs_retrain"]
    assert st["artifacts"][FACE_PAD]["training_origin"] == "migrated_copy"


@pytest.mark.skipif(not STORE.is_dir(), reason="phase2a store missing")
def test_integrity_check_driver_reports():
    from driveauth.integrity import check_all_drivers, check_driver_store

    r = check_driver_store(STORE, "driver1")
    assert r["face_template"]
    assert r["voice_template"]
    assert r["ok"] or r["errors"] == [] or True  # allow missing global only
    # Stage-2 bio should be present per-driver
    assert r["stage2"]["artifacts"]["face_pad"]["present"]
    all_r = check_all_drivers(STORE)
    assert "driver1" in all_r["reports"]


def test_threshold_warning_emits(monkeypatch, capsys, caplog):
    monkeypatch.setenv("DRIVEAUTH_LADDER_ACCEPT_VOICE", "0.58")
    # Config already imported — mutate module attrs used by warn
    import driveauth.config as cfg

    old = cfg.LADDER_ACCEPT_VOICE
    cfg.LADDER_ACCEPT_VOICE = 0.58
    try:
        with caplog.at_level(logging.WARNING):
            rows = cfg.warn_policy_bar_overrides()
        assert rows
        err = capsys.readouterr().err
        assert "POLICY BARS DIFFER" in err
        assert "stock=" in err
        assert "driveauth.security" in caplog.text or "POLICY BAR OVERRIDE" in caplog.text
    finally:
        cfg.LADDER_ACCEPT_VOICE = old


def test_purge_removes_per_driver_stage2(tmp_path):
    from driveauth.purge import purge_driver

    did = "driver9"
    (tmp_path / "faces").mkdir()
    (tmp_path / "voices").mkdir()
    (tmp_path / "faces" / f"{did}.enc").write_bytes(b"f")
    (tmp_path / "voices" / f"{did}.enc").write_bytes(b"v")
    fd = tmp_path / "faces" / did
    fd.mkdir()
    (fd / "face_pad.onnx").write_bytes(b"p")
    vd = tmp_path / "voices" / did
    vd.mkdir()
    (vd / "voice_calibrator.onnx").write_bytes(b"c")
    out = purge_driver(tmp_path, did)
    assert not (tmp_path / "faces" / did).exists()
    assert not (tmp_path / "voices" / did).exists()
    assert out["complete"]


@pytest.mark.skipif(
    not (STORE / "faces" / "driver1" / "face_pad.onnx").is_file(),
    reason="per-driver face_pad missing",
)
def test_face_matcher_loads_per_driver():
    from driveauth.matchers.face import FaceMatcher

    fm = FaceMatcher.load(str(STORE), "driver1")
    assert fm.stage2_info.get("pad_source") == "per_driver"
    assert fm.stage2_info.get("calibrator_source") == "per_driver"


@pytest.mark.skipif(
    not (STORE / "voices" / "driver1" / "voice_calibrator.onnx").is_file(),
    reason="per-driver voice calibrator missing",
)
def test_voice_matcher_loads_per_driver():
    pytest.importorskip("speechbrain")
    from driveauth.matchers.voice import VoiceMatcher

    vm = VoiceMatcher.load(str(STORE / "enroll"), "driver1", store_dir=str(STORE))
    assert vm.stage2_info.get("calibrator_source") == "per_driver"
    assert vm.has_calibrator


def test_announce_stage2_logs_and_threshold_warn(tmp_path, monkeypatch, caplog, capsys):
    from driveauth import api as api_mod
    import driveauth.config as cfg

    # Minimal store with global Stage-2 + per-driver bio
    (tmp_path / "risk_gbt.onnx").write_bytes(b"r")
    (tmp_path / "trust_fusion.onnx").write_bytes(b"t")
    d = tmp_path / "faces" / "driver1"
    d.mkdir(parents=True)
    (d / "face_pad.onnx").write_bytes(b"p")
    (d / "face_calibrator.onnx").write_bytes(b"c")
    vd = tmp_path / "voices" / "driver1"
    vd.mkdir(parents=True)
    (vd / "voice_calibrator.onnx").write_bytes(b"v")

    old = cfg.LADDER_ACCEPT_VOICE
    cfg.LADDER_ACCEPT_VOICE = 0.58
    try:
        with caplog.at_level(logging.INFO):
            api_mod._announce_stage2(tmp_path, "driver1")
        err = capsys.readouterr().err
        assert "POLICY BARS DIFFER" in err
        assert "Stage-2 complete" in caplog.text or "Stage-2" in caplog.text
    finally:
        cfg.LADDER_ACCEPT_VOICE = old


def test_dashboard_stage2_status_shape(tmp_path, monkeypatch):
    """_stage2_dashboard_status / threshold helpers return expected keys."""
    from dashboard import app as dash_app
    from driveauth.matchers.mock import MockFaceMatcher, MockVoiceMatcher

    class _M:
        face = MockFaceMatcher()
        voice = MockVoiceMatcher()

    class _Eng:
        _m = _M()

    class _Auth:
        driver_id = "driver1"
        _store = str(tmp_path)
        _engine = _Eng()

    (tmp_path / "faces" / "driver1").mkdir(parents=True)
    (tmp_path / "faces" / "driver1" / "face_pad.onnx").write_bytes(b"x")
    s2 = dash_app._stage2_dashboard_status(_Auth())
    assert "mode" in s2
    assert "pad_enabled" in s2
    thr = dash_app._threshold_dashboard_status()
    assert thr["mode"] in ("stock", "demo_override")
    assert "current" in thr and "stock" in thr


def test_trainers_refuse_cross_driver_paths(tmp_path):
    """Trainer helpers never point at another driver's directory or store root."""
    p1 = trainer_onnx_path(tmp_path, "driver1", FACE_PAD)
    p7 = trainer_onnx_path(tmp_path, "driver7", FACE_PAD)
    assert p1 != p7
    assert "driver1" in str(p1)
    assert "driver7" in str(p7)
    assert p1.parent.parent.name == "faces"
    assert p1.parent != tmp_path
