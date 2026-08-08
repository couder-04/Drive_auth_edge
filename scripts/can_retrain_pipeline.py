#!/usr/bin/env python3
"""Orchestrate real CAN behavioral retrain from fleet logger output.

Expects ``data/<driver>/behavioral/{genuine,attack}/can_*.csv`` produced by
``hardware/can_logger.py`` (or copied from a pilot vehicle).

Usage::

    python scripts/can_retrain_pipeline.py \\
        --real-data-dir /var/driveauth/fleet/vehicle_03 \\
        --store ./driveauth_store \\
        --driver driver1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _count_windows(data_dir: Path) -> int:
    n = 0
    beh = data_dir / "behavioral"
    if not beh.is_dir():
        return 0
    for split in ("genuine", "attack"):
        d = beh / split
        if d.is_dir():
            n += len(list(d.glob("can_*.csv")))
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="CAN logger → behavioral bake-off pipeline")
    ap.add_argument("--real-data-dir", type=Path, required=True)
    ap.add_argument("--store", type=Path, default=Path("./driveauth_store"))
    ap.add_argument("--driver", default="driver1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data_dir = args.real_data_dir.expanduser().resolve()
    store = args.store.expanduser().resolve()
    n = _count_windows(data_dir)
    if n == 0:
        print(
            f"ERROR: no can_*.csv under {data_dir}/behavioral/{{genuine,attack}} — "
            "run hardware/can_logger.py on a live bus first",
            file=sys.stderr,
        )
        return 1

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "train_behavioral_bakeoff.py"),
        "--store",
        str(store),
        "--driver",
        args.driver,
        "--real-data-dir",
        str(data_dir),
        "--real-repeat",
        "3",
    ]
    print(" ".join(cmd))
    if args.dry_run:
        return 0
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
