"""Phase 10 — CAN logger schema compatibility with synthetic txn generator."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from driveauth.matchers.behavioral import BEHAVIORAL_FEATURE_KEYS
from hardware.can_logger import (
    TXN_CSV_COLUMNS,
    CanLogger,
    CanLoggerConfig,
    GpsFix,
    txn_schema_dtypes,
)


class _FakeBus:
    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.shutdown_called = False

    def recv(self, timeout=None):
        if self._messages:
            return self._messages.pop(0)
        return None

    def shutdown(self):
        self.shutdown_called = True


def test_txn_columns_match_generate_risk_txns_export():
    # Keep in lockstep with scripts/generate_risk_txns.py export_cols.
    expected = [
        "amount",
        "beneficiary",
        "beneficiary_known",
        "hour",
        "speed_kmh",
        "in_trusted_zone",
        "dist_from_home_km",
        "ignition_on",
        "is_tunnel",
        "behavioral_score",
        "label",
        "driver_id",
    ]
    assert list(TXN_CSV_COLUMNS) == expected
    assert set(txn_schema_dtypes()) == set(TXN_CSV_COLUMNS)


def test_can_logger_writes_compatible_txn_and_behavioral_csvs(tmp_path: Path):
    logger = CanLogger(
        out_dir=tmp_path / "fleet1",
        config=CanLoggerConfig(
            driver_id="drv_0001",
            home_lat=12.97,
            home_lon=77.59,
            trusted_zone_radius_km=10.0,
            window_rows=10,
        ),
        bus_factory=lambda: _FakeBus(),
        gps_provider=lambda: GpsFix(
            lat=12.98, lon=77.60, accuracy_m=5.0, speed_kmh=42.0
        ),
    )
    assert logger.start() is True

    for i in range(10):
        logger.ingest_frame(
            arbitration_id=0x100,
            data=bytes([(i * 17) % 256 for _ in range(8)]),
            gps=GpsFix(lat=12.98, lon=77.60, accuracy_m=5.0, speed_kmh=40.0 + i),
        )
    row = logger.record_txn_snapshot(
        amount=500.0,
        beneficiary="Mom",
        beneficiary_known=1,
        label="legit",
        behavioral_score=0.9,
    )
    logger.stop()

    # Behavioral window schema.
    windows = list((tmp_path / "fleet1" / "behavioral" / "genuine").glob("can_*.csv"))
    assert len(windows) >= 1
    with windows[0].open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == list(BEHAVIORAL_FEATURE_KEYS)
        rows = list(reader)
        assert len(rows) == 10
        for r in rows:
            for k in BEHAVIORAL_FEATURE_KEYS:
                float(r[k])  # dtype: float-parseable

    # Risk txn schema — identical columns to synthetic generator.
    txn_path = tmp_path / "fleet1" / "transaction" / "txns_real.csv"
    assert txn_path.exists()
    with txn_path.open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == list(TXN_CSV_COLUMNS)
        txn_rows = list(reader)
    assert len(txn_rows) == 1
    assert txn_rows[0]["driver_id"] == "drv_0001"
    assert float(txn_rows[0]["amount"]) == 500.0
    assert int(txn_rows[0]["beneficiary_known"]) in (0, 1)
    assert txn_rows[0]["label"] in ("legit", "suspicious")
    # dtypes: all TXN columns present and castable per logical map
    dtypes = txn_schema_dtypes()
    for col, kind in dtypes.items():
        val = txn_rows[0][col]
        if kind == "float":
            float(val)
        elif kind == "int":
            int(float(val))
        else:
            assert isinstance(val, str)

    assert row["speed_kmh"] >= 0.0


def test_synthetic_and_real_txn_columns_identical():
    """Import generator export list without running the full generator."""
    import ast
    from pathlib import Path

    src = Path("scripts/generate_risk_txns.py").read_text()
    # Locate export_cols assignment in main().
    tree = ast.parse(src)
    found = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "export_cols":
                    found = ast.literal_eval(node.value)
    assert found is not None
    assert tuple(found) == TXN_CSV_COLUMNS
