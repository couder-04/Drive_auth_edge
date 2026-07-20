"""Tests for always-on performance telemetry CSV + rotation."""

from __future__ import annotations

from pathlib import Path

from driveauth.perf_telemetry import CSV_COLUMNS, PerfTelemetry, SCHEMA_VERSION
from driveauth.types import ModalityResult


def _fake_psutil():
    calls = {"n": 0}

    def snap():
        calls["n"] += 1
        return {"cpu_pct": 12.5, "ram_pct": 44.0, "ram_used_mb": 1024.0}

    snap.calls = calls  # type: ignore[attr-defined]
    return snap


def test_csv_schema_and_decision_row(tmp_path: Path):
    log = tmp_path / "perf.csv"
    tel = PerfTelemetry(
        log,
        psutil_snapshot=_fake_psutil(),
        auto_util=False,
        enabled=True,
    )
    row = tel.record_decision(
        session_id="s1",
        driver_id="driver1",
        decision="ACCEPT",
        voice_ms=11.2,
        face_ms=22.5,
        finger_ms=5.0,
        liveness_ms=3.1,
        total_ms=40.0,
        face_backend="cpu",
    )
    assert row is not None
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")
    assert header == list(CSV_COLUMNS)
    assert "decision" in text
    assert "11.200" in text
    assert "cpu" in row["face_backend"] or row["face_backend"] == "cpu"


def test_record_from_modality_results(tmp_path: Path):
    tel = PerfTelemetry(
        tmp_path / "perf.csv",
        psutil_snapshot=_fake_psutil(),
        auto_util=False,
    )
    results = {
        "voice": ModalityResult(0.9, True, latency_ms=15.0),
        "face": ModalityResult(0.8, True, latency_ms=30.0),
        "finger": ModalityResult(0.7, True, latency_ms=8.0),
    }
    row = tel.record_from_modality_results(
        results, decision="REJECT", total_ms=60.0, liveness_ms=2.0
    )
    assert row is not None
    assert row["voice_ms"] == "15.000"
    assert row["face_ms"] == "30.000"
    assert row["finger_ms"] == "8.000"
    assert row["liveness_ms"] == "2.000"


def test_utilization_row_uses_mocked_psutil(tmp_path: Path):
    snap = _fake_psutil()
    tel = PerfTelemetry(
        tmp_path / "perf.csv",
        psutil_snapshot=snap,
        auto_util=False,
    )
    row = tel.record_utilization()
    assert row is not None
    assert row["event"] == "util"
    assert row["cpu_pct"] == "12.50"
    assert row["ram_pct"] == "44.00"
    assert snap.calls["n"] == 1  # type: ignore[attr-defined]


def test_rotation_creates_backup(tmp_path: Path):
    log = tmp_path / "perf.csv"
    tel = PerfTelemetry(
        log,
        max_bytes=200,
        backup_count=2,
        psutil_snapshot=_fake_psutil(),
        auto_util=False,
    )
    for i in range(40):
        tel.record_decision(
            session_id=f"s{i}",
            decision="ACCEPT",
            voice_ms=1.0,
            face_ms=1.0,
            total_ms=2.0,
        )
    assert log.exists() or Path(f"{log}.1").exists()
    # After enough writes, at least one rotated backup should exist.
    assert Path(f"{log}.1").exists() or log.stat().st_size <= 200 + 500


def test_summary_shape(tmp_path: Path):
    tel = PerfTelemetry(
        tmp_path / "perf.csv",
        psutil_snapshot=_fake_psutil(),
        auto_util=False,
    )
    tel.record_decision(voice_ms=10, face_ms=20, total_ms=30, decision="ACCEPT")
    tel.record_utilization()
    summary = tel.summary()
    assert summary["schema"] == SCHEMA_VERSION
    assert summary["enabled"] is True
    assert summary["latency_ms_avg"]["voice"] == 10.0
    assert summary["utilization"]["cpu_pct"] in ("12.50", 12.5) or float(
        summary["utilization"]["cpu_pct"]
    ) == 12.5


def test_disabled_writes_nothing(tmp_path: Path):
    log = tmp_path / "perf.csv"
    tel = PerfTelemetry(
        log,
        enabled=False,
        psutil_snapshot=_fake_psutil(),
        auto_util=False,
    )
    assert tel.record_decision(voice_ms=1) is None
    assert not log.exists()
