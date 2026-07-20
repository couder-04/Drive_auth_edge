#!/usr/bin/env python3
"""Phase 1b — collect Thor hardware + mock-auth latency into phases/thor.txt.

Usage on Thor:
  export DRIVEAUTH_USE_MOCK=1
  python scripts/phase1b_thor_bench.py --out phases/thor.txt

Phase 1 latency budget (mock auth): p95 ≤ MOCK_AUTH_P95_MS (default 10 ms).
See phases/phase1.md.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Phase 1 success bar: mock-pipeline decision path must stay interactive.
MOCK_AUTH_P95_MS = 10.0


def _run(cmd: list[str], timeout: float = 15.0) -> str:
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (out.stdout or out.stderr or "").strip()
    except Exception as exc:
        return f"(failed: {exc})"


def _ort_providers() -> str:
    try:
        import onnxruntime as ort  # type: ignore

        return f"ORT {ort.__version__} providers={ort.get_available_providers()}"
    except Exception as exc:
        return f"ORT unavailable ({exc})"


def _rss_kb(pid: int) -> int | None:
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    # macOS fallback (unlikely on Thor)
    try:
        out = _run(["ps", "-o", "rss=", "-p", str(pid)])
        return int(out.strip()) if out.strip().isdigit() else None
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1b Thor bench")
    parser.add_argument(
        "--out",
        default=str(ROOT / "phases" / "thor.txt"),
        help="Output profile path",
    )
    parser.add_argument("--n", type=int, default=50, help="Auth iterations")
    args = parser.parse_args()

    os.environ.setdefault("DRIVEAUTH_USE_MOCK", "1")
    os.environ.setdefault("DRIVEAUTH_FINGERPRINT_AVAILABLE", "0")

    from driveauth import DriveAuth
    from testsupport import good_audio, mature

    pid = os.getpid()
    uname = platform.uname()
    py = sys.version.split()[0]

    nvidia = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    if not nvidia or nvidia.startswith("(failed"):
        nvidia = _run(["nvidia-smi"])
    tegrastats = _run(["tegrastats", "--interval", "1000"], timeout=2.0)
    # tegrastats runs forever — ignore / use jtop note
    if "failed" in tegrastats or not tegrastats:
        tegrastats = "(run jtop / tegrastats manually if available)"

    auth = DriveAuth.load(tempfile.mkdtemp(), use_mock_matchers=True)
    mature(auth)
    audio = good_audio()
    # Warmup — exclude import/ORT cold-start from the measured window.
    for _ in range(5):
        auth.authenticate(
            audio_np=audio,
            amount=50,
            beneficiary_known=True,
            beneficiary="Mom",
        )
    times: list[float] = []
    for _ in range(args.n):
        t0 = time.perf_counter()
        auth.authenticate(
            audio_np=audio,
            amount=50,
            beneficiary_known=True,
            beneficiary="Mom",
        )
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    n = len(times)
    p50 = times[n // 2]
    p95 = times[min(n - 1, int(n * 0.95))]
    mx = times[-1]
    rss = _rss_kb(pid)
    budget_ok = p95 <= MOCK_AUTH_P95_MS
    budget_line = (
        f"Latency budget: MOCK_AUTH_P95_MS={MOCK_AUTH_P95_MS:.1f} → "
        f"p95={p95:.1f}ms {'PASS' if budget_ok else 'FAIL'}"
    )

    lines = [
        "Phase: 1b (NVIDIA Thor — mock pipeline)",
        f"Date: {date.today().isoformat()}",
        f"Status: {'PASS' if budget_ok else 'FAIL'} (budget check; fill pass checks below)",
        "",
        f"Device: {uname.system} {uname.release} · {uname.machine} · node={uname.node}",
        f"Python: {py}",
        f"DRIVEAUTH_USE_MOCK={os.environ.get('DRIVEAUTH_USE_MOCK', '1')}",
        "",
        "GPU / nvidia-smi:",
        nvidia or "(nvidia-smi not found)",
        "",
        _ort_providers(),
        "",
        f"Auth latency: n={n}  p50={p50:.1f}ms  p95={p95:.1f}ms  max={mx:.1f}ms",
        f"RSS: {rss} KB" if rss is not None else "RSS: (unavailable)",
        "  (compare Mac Phase 1a: p50=0.7ms · RSS≈28.2 MB)",
        budget_line,
        "",
        "Pass checks (fill manually after pytest/demo/dashboard):",
        "  [ ] pytest -q",
        "  [ ] driveauth-demo ACCEPT micro",
        "  [ ] dashboard on 0.0.0.0:8765",
        "  [ ] audit log grows",
        "",
        "Next: optional Phase 2a on Thor (ECAPA + MobileFaceNet latency)",
        "See phases/phase1.md for Phase 1 completion record.",
        "",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    print(out.read_text())
    print(f"wrote {out}")
    if not budget_ok:
        raise SystemExit(
            f"FAIL: mock auth p95={p95:.1f}ms exceeds Phase 1 budget "
            f"{MOCK_AUTH_P95_MS:.1f}ms"
        )


if __name__ == "__main__":
    main()
