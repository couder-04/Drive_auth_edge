#!/usr/bin/env python3
"""Benchmark Hailo vs ONNX face inference (latency only).

Requires ``DRIVEAUTH_HAILO_HW_TEST=1`` and a loaded ``.hef`` for on-device runs.
Without hardware, prints configuration status and exits 0.

Usage::

    DRIVEAUTH_HAILO_HW_TEST=1 DRIVEAUTH_FACE_BACKEND=hailo \\
        python scripts/bench_hailo_face.py --store ./driveauth_store --driver driver1
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path


def _bench(fn, *, n: int = 20) -> dict:
    times: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return {
        "n": n,
        "p50_ms": round(statistics.median(times), 2),
        "p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Hailo face backend latency bench")
    ap.add_argument("--store", type=Path, default=Path("./driveauth_store"))
    ap.add_argument("--driver", default="driver1")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    if os.getenv("DRIVEAUTH_HAILO_HW_TEST", "0") != "1":
        print("SKIP: set DRIVEAUTH_HAILO_HW_TEST=1 for on-device benchmark")
        return 0

    os.environ.setdefault("DRIVEAUTH_FACE_BACKEND", "hailo")
    from hardware.hailo_face import HailoFaceMatcher

    matcher = HailoFaceMatcher.load(str(args.store), args.driver)
    if not getattr(matcher, "ready", False):
        print("Hailo matcher not ready — check HEF path and hailo_platform install")
        return 1

    import numpy as np

    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    matcher.inject_bgr(frame)

    stats = _bench(matcher.capture_and_score, n=args.n)
    print(f"Hailo face p50={stats['p50_ms']}ms p95={stats['p95_ms']}ms n={stats['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
