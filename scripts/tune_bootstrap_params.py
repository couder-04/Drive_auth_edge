#!/usr/bin/env python3
"""Recommend bootstrap maturity + timing-pad values from audit/profile data.

Reads driver profiles and audit logs under a store directory and prints
suggested ``DRIVEAUTH_BOOTSTRAP_*`` / ``DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS``
values for a fleet env file.

Usage::

    python scripts/tune_bootstrap_params.py --store ./driveauth_store
    python scripts/tune_bootstrap_params.py --store ./store --write phases/fleet_bootstrap.env
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path


def _load_profiles(store: Path) -> list[dict]:
    prof_dir = store / "profiles"
    if not prof_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in prof_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict) and "txn_count" in v:
                    rows.append(v)
            if "txn_count" in data:
                rows.append(data)
    return rows


def _audit_decision_ms(audit_path: Path) -> list[float]:
    if not audit_path.is_file():
        return []
    gaps: list[float] = []
    prev_ts: float | None = None
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = entry.get("ts") or entry.get("timestamp")
        if ts is None:
            continue
        try:
            cur = float(ts)
        except (TypeError, ValueError):
            continue
        if prev_ts is not None and cur >= prev_ts:
            gaps.append((cur - prev_ts) * 1000.0)
        prev_ts = cur
    return gaps


def recommend(store: Path) -> dict:
    from driveauth import config

    profiles = _load_profiles(store)
    txn_counts = [int(p.get("txn_count", 0)) for p in profiles]
    now = time.time()
    day_spans: list[float] = []
    for p in profiles:
        created = float(p.get("created_at", 0) or 0)
        last = float(p.get("last_txn_at", 0) or 0)
        if created > 0 and last > created:
            day_spans.append((last - created) / 86400.0)

    p50_txn = int(statistics.median(txn_counts)) if txn_counts else config.BOOTSTRAP_MIN_TXNS
    p90_txn = int(sorted(txn_counts)[int(0.9 * (len(txn_counts) - 1))]) if len(txn_counts) > 1 else max(p50_txn, config.BOOTSTRAP_MIN_TXNS)
    p50_days = float(statistics.median(day_spans)) if day_spans else config.BOOTSTRAP_MIN_DAYS

    gaps = _audit_decision_ms(store / "audit" / "driveauth_events.jsonl")
    p95_ms = float(statistics.quantiles(gaps, n=20)[-1]) if len(gaps) >= 5 else 0.0
    quantum_ms = max(0.0, round(p95_ms / 50.0) * 50.0) if p95_ms > 0 else 0.0

    min_txns = max(3, min(p90_txn, 25))
    min_days = max(1.0, min(round(p50_days, 1), 14.0))

    return {
        "drivers": len(profiles),
        "txn_p50": p50_txn,
        "txn_p90": p90_txn,
        "days_p50": round(p50_days, 2),
        "audit_gap_p95_ms": round(p95_ms, 1),
        "recommended": {
            "DRIVEAUTH_BOOTSTRAP_MIN_TXNS": min_txns,
            "DRIVEAUTH_BOOTSTRAP_MIN_DAYS": min_days,
            "DRIVEAUTH_ESCALATION_CONSTANT_TIME_MS": quantum_ms,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Tune bootstrap + timing-pad from store data")
    ap.add_argument("--store", type=Path, default=Path("./driveauth_store"))
    ap.add_argument("--write", type=Path, help="Write suggested env file")
    args = ap.parse_args()

    result = recommend(args.store.expanduser().resolve())
    print(json.dumps(result, indent=2))

    if args.write:
        lines = [
            "# Auto-generated bootstrap/timing suggestions — review before fleet ship",
            f"# drivers={result['drivers']} txn_p90={result['txn_p90']} days_p50={result['days_p50']}",
        ]
        for k, v in result["recommended"].items():
            lines.append(f"{k}={v}")
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.write}")


if __name__ == "__main__":
    main()
