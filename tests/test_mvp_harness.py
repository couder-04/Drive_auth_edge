"""Smoke test for the stress harness (short, mock-only)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stress_harness_short_run():
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "stress_test.py"),
        "--seconds",
        "2",
        "--iterations",
        "5",
        "--workers",
        "1",
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "stress summary" in proc.stdout
    assert "ok / err" in proc.stdout


def test_bootstrap_check_only():
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "bootstrap.py"),
        "--check-only",
        "--store",
        str(ROOT / "driveauth_store_phase2a"),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    # Exit 0 (ready), 1 (missing stage1), or 2 (missing stage2) are all "script works"
    assert proc.returncode in (0, 1, 2), proc.stderr + proc.stdout
    assert "bootstrap status" in proc.stdout.lower() or "Stage-1" in proc.stdout
