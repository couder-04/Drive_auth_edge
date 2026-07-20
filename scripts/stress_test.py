#!/usr/bin/env python3
"""Stress / soak harness for DriveAuth authentication loop (MVP).

Runs a configurable number of mock authenticate cycles while sampling
RSS/CPU and handling SIGINT/SIGTERM for graceful shutdown.

Examples:
  python scripts/stress_test.py --seconds 30
  python scripts/stress_test.py --iterations 500 --workers 2
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class Stats:
    ok: int = 0
    err: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    peak_rss_mb: float = 0.0
    stop: bool = False


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def _cpu_pct() -> float:
    try:
        import psutil

        return float(psutil.Process(os.getpid()).cpu_percent(interval=None))
    except Exception:
        return 0.0


def worker(stats: Stats, store: str, iterations: int | None, deadline: float) -> None:
    from testsupport import good_audio, make_auth, mature

    auth = make_auth(store_dir=store)
    mature(auth)
    audio = good_audio()
    n = 0
    while not stats.stop:
        if iterations is not None and n >= iterations:
            break
        if time.monotonic() >= deadline:
            break
        t0 = time.perf_counter()
        try:
            auth.authenticate(
                audio_np=audio,
                amount=50.0,
                beneficiary="stress",
                beneficiary_known=True,
                event="stress",
            )
            stats.ok += 1
        except Exception:
            stats.err += 1
        dt = (time.perf_counter() - t0) * 1000.0
        stats.latencies_ms.append(dt)
        rss = _rss_mb()
        if rss > stats.peak_rss_mb:
            stats.peak_rss_mb = rss
        n += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="DriveAuth stress / soak harness")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--store", default="")
    args = parser.parse_args()

    store = args.store or tempfile.mkdtemp(prefix="driveauth_stress_")
    Path(store).mkdir(parents=True, exist_ok=True)
    stats = Stats()

    def _stop(*_args):
        stats.stop = True
        print("\nshutdown signal — finishing current iteration…", flush=True)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    deadline = time.monotonic() + float(args.seconds)
    per_worker = None
    if args.iterations is not None:
        per_worker = max(1, args.iterations // max(1, args.workers))

    print(
        f"stress start: workers={args.workers} seconds={args.seconds} "
        f"iterations={args.iterations} store={store}"
    )
    _cpu_pct()  # prime
    threads = [
        threading.Thread(
            target=worker,
            args=(stats, store, per_worker, deadline),
            daemon=True,
        )
        for _ in range(max(1, args.workers))
    ]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    lats = sorted(stats.latencies_ms)
    def pct(p: float) -> float:
        if not lats:
            return 0.0
        idx = min(len(lats) - 1, int(round((p / 100.0) * (len(lats) - 1))))
        return lats[idx]

    print("\n=== stress summary ===")
    print(f"elapsed_s     : {elapsed:.2f}")
    print(f"ok / err      : {stats.ok} / {stats.err}")
    print(f"throughput    : {stats.ok / max(elapsed, 1e-6):.1f} auth/s")
    print(f"latency_ms p50: {pct(50):.1f}")
    print(f"latency_ms p95: {pct(95):.1f}")
    print(f"latency_ms p99: {pct(99):.1f}")
    print(f"peak_rss_mb   : {stats.peak_rss_mb:.1f}")
    print(f"cpu_percent   : {_cpu_pct():.1f}")
    return 0 if stats.err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
