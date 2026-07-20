#!/usr/bin/env python3
"""Bootstrap DriveAuth Edge store for a fresh clone (MVP).

Downloads Stage-1 pretrained models (ECAPA + MobileFaceNet) and verifies
Stage-2 ONNX heads. Never silently falls back — prints a clear checklist.

Usage:
  python scripts/bootstrap.py
  python scripts/bootstrap.py --store ./driveauth_store_phase2a --skip-voice
  python scripts/bootstrap.py --check-only

Exit codes:
  0 — store ready (or check passed)
  1 — missing required artifacts / setup failed
  2 — Stage-2 heads missing (base models OK; train or copy heads)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stage-1 (required for real matchers)
STAGE1_FACE = ("mobilefacenet.onnx", "models/mobilefacenet.onnx")
STAGE1_VOICE_DIR = Path("models/ecapa_voxceleb")

# Stage-2 heads (required when DRIVEAUTH_REQUIRE_STAGE2=1)
STAGE2_ARTIFACTS = (
    "risk_gbt.onnx",
    "trust_fusion.onnx",
    "face_pad.onnx",
    "face_calibrator.onnx",
    "voice_calibrator.onnx",
)


def _exists_any(store: Path, names: tuple[str, ...]) -> bool:
    return any((store / n).is_file() for n in names)


def check_store(store: Path) -> dict:
    face_ok = _exists_any(store, STAGE1_FACE) or (store / "mobilefacenet_int8.onnx").is_file()
    voice_ok = (store / STAGE1_VOICE_DIR).is_dir() and any(
        (store / STAGE1_VOICE_DIR).glob("*")
    )
    stage2 = {name: (store / name).is_file() for name in STAGE2_ARTIFACTS}
    return {
        "store": str(store.resolve()),
        "face_model": face_ok,
        "voice_model": voice_ok,
        "stage2": stage2,
        "stage2_complete": all(stage2.values()),
    }


def print_report(report: dict) -> None:
    print("\n=== DriveAuth bootstrap status ===")
    print("store:", report["store"])
    print("  Stage-1 face ONNX :", "OK" if report["face_model"] else "MISSING")
    print("  Stage-1 ECAPA     :", "OK" if report["voice_model"] else "MISSING")
    print("  Stage-2 heads:")
    for name, ok in report["stage2"].items():
        print(f"    {name}: {'OK' if ok else 'MISSING'}")
    if report["stage2_complete"] and report["face_model"] and report["voice_model"]:
        print("\nStore is ready for real matchers (DRIVEAUTH_USE_MOCK=0).")
    else:
        print("\nNext steps:")
        if not report["face_model"] or not report["voice_model"]:
            print("  python scripts/phase2a_setup.py --store", report["store"])
        missing = [k for k, v in report["stage2"].items() if not v]
        if missing:
            print("  Train / export missing Stage-2 heads, e.g.:")
            print("    pip install -e '.[train,onnx]'")
            print("    python scripts/train_risk_gbt.py --store", report["store"])
            print("    python scripts/train_trust_fusion.py --store", report["store"])
            print("    python scripts/train_face_pad.py --store", report["store"])
            print("    python scripts/train_face_calibrator.py --store", report["store"])
            print("    python scripts/train_voice_calibrator.py --store", report["store"])
            print("  Or copy a complete store, then re-run --check-only.")
        print(
            "  Demo without models: export DRIVEAUTH_USE_MOCK=1 "
            "(never silent — mock is explicit)."
        )


def run_phase2a(store: Path, *, skip_voice: bool, skip_face: bool) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / "phase2a_setup.py"), "--store", str(store)]
    if skip_voice:
        cmd.append("--skip-voice")
    if skip_face:
        cmd.append("--skip-face")
    print("→", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def ensure_api_key_hint() -> None:
    if os.getenv("DRIVEAUTH_DASHBOARD_API_KEY"):
        return
    print(
        "\nNote: set DRIVEAUTH_DASHBOARD_API_KEY in secrets.env for dashboard admin "
        "routes (or DRIVEAUTH_ALLOW_INSECURE_DASHBOARD=1 for localhost demos only)."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap DriveAuth Edge models")
    parser.add_argument(
        "--store",
        default=str(ROOT / "driveauth_store_phase2a"),
        help="Store directory for models + templates",
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--skip-voice", action="store_true")
    parser.add_argument("--skip-face", action="store_true")
    parser.add_argument(
        "--require-stage2",
        action="store_true",
        help="Exit 2 when Stage-2 ONNX heads are missing",
    )
    parser.add_argument(
        "--write-status",
        default="",
        help="Optional path to write JSON status report",
    )
    args = parser.parse_args()
    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)

    print("DriveAuth Edge bootstrap")
    print("========================")
    print("This never silently falls back to heuristic/mock models.")
    print("Mock path is explicit: DRIVEAUTH_USE_MOCK=1")
    print("Optional hybrid: DRIVEAUTH_ALLOW_MOCK_FALLBACK=1\n")

    if not args.check_only:
        need = check_store(store)
        if not need["face_model"] or not need["voice_model"]:
            print("Downloading / installing Stage-1 pretrained models…")
            try:
                run_phase2a(store, skip_voice=args.skip_voice, skip_face=args.skip_face)
            except subprocess.CalledProcessError as exc:
                print("Stage-1 setup failed:", exc, file=sys.stderr)
                return 1
        else:
            print("Stage-1 models already present — skipping download.")

    report = check_store(store)
    print_report(report)
    ensure_api_key_hint()

    if args.write_status:
        out = Path(args.write_status)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("Wrote", out)

    if not report["face_model"] or not report["voice_model"]:
        return 1
    if (args.require_stage2 or os.getenv("DRIVEAUTH_REQUIRE_STAGE2", "0") == "1") and not report[
        "stage2_complete"
    ]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
