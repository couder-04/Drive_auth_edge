#!/usr/bin/env python3
"""Stage 2 overfit audit — voice/face/PAD/trust_fusion JSON sidecars.

Checks train/val gap, LOO AUC, shuffled-label collapse. Prefers per-driver
bio heads under ``faces/{id}/`` and ``voices/{id}/``; falls back to legacy
store-root JSON for compatibility.

Usage:
  python scripts/overfit_audit_stage2.py --store driveauth_store_phase2a
  python scripts/overfit_audit_stage2.py --store … --driver-id driver1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth.stage2_artifacts import (  # noqa: E402
    list_enrolled_driver_ids,
    per_driver_json_relpath,
)

# (artifact stem, min_loo, max_gap)
BIO_CHECKS = (
    ("voice_calibrator", 0.70, 0.20),
    ("face_pad", 0.60, 0.25),
    ("face_calibrator", 0.55, 0.25),
)
GLOBAL_CHECKS = (
    ("trust_fusion.json", 0.80, 0.15),
)


def _resolve_meta(store: Path, stem: str, driver_id: str | None) -> Path | None:
    if driver_id:
        rel = per_driver_json_relpath(stem, driver_id)
        p = store / rel
        if p.is_file():
            return p
    legacy = store / f"{stem}.json"
    if legacy.is_file():
        return legacy
    return None


def _audit_meta(path: Path, min_loo: float, max_gap: float, failures: list[str]) -> None:
    meta = json.loads(path.read_text())
    loo = float(meta.get("loo_auc", 0.0))
    gap = float(meta.get("gap", 0.0))
    shuf = float(meta.get("shuffled_loo_auc", 0.5))
    print(f"{path}: loo_auc={loo:.4f} gap={gap:+.4f} shuffled={shuf:.4f}")
    name = path.name
    if loo < min_loo:
        failures.append(f"{path}: loo_auc {loo:.3f} < {min_loo}")
    if gap > max_gap:
        if loo < min_loo + 0.1:
            failures.append(f"{path}: gap {gap:.3f} > {max_gap}")
        else:
            print(f"  (gap soft-pass: strong LOO={loo:.3f})")
    if abs(shuf - 0.5) > 0.30 and loo < 0.75:
        failures.append(f"{path}: shuffled AUC {shuf:.3f} suspicious")

    onnx = path.with_suffix(".onnx")
    if not onnx.exists():
        failures.append(f"missing ONNX for {name}")
    else:
        try:
            import numpy as np
            import onnxruntime as ort

            sess = ort.InferenceSession(str(onnx), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            n = inp.shape[1] if isinstance(inp.shape[1], int) else 1
            sess.run(None, {inp.name: np.zeros((1, n), dtype=np.float32)})
            print(f"  ORT OK {onnx.name}")
        except Exception as exc:
            failures.append(f"ORT smoke {onnx.name}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument(
        "--driver-id",
        default="",
        help="Audit one driver (default: all enrolled with per-driver heads, else legacy)",
    )
    args = ap.parse_args()

    failures: list[str] = []
    drivers = [args.driver_id] if args.driver_id else list_enrolled_driver_ids(args.store)
    if not drivers:
        drivers = [None]  # type: ignore[list-item]

    checked_any = False
    for did in drivers:
        for stem, min_loo, max_gap in BIO_CHECKS:
            path = _resolve_meta(args.store, stem, did)
            if path is None:
                if did:
                    failures.append(f"missing {stem} for {did}")
                else:
                    failures.append(f"missing {stem}.json")
                continue
            checked_any = True
            _audit_meta(path, min_loo, max_gap, failures)

    for name, min_loo, max_gap in GLOBAL_CHECKS:
        path = args.store / name
        if not path.exists():
            failures.append(f"missing {name}")
            continue
        checked_any = True
        _audit_meta(path, min_loo, max_gap, failures)

    if not checked_any:
        failures.append("no Stage-2 sidecars found")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print("\nOK")


if __name__ == "__main__":
    main()
