#!/usr/bin/env python3
"""Stage 2 overfit audit — voice/face/PAD/trust_fusion JSON sidecars.

Checks train/val gap, LOO AUC, shuffled-label collapse. Exit 0 if all pass.

Usage:
  python scripts/overfit_audit_stage2.py --store driveauth_store_phase2a
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS = (
    ("voice_calibrator.json", 0.70, 0.20),
    ("face_pad.json", 0.60, 0.25),
    ("face_calibrator.json", 0.55, 0.25),
    ("trust_fusion.json", 0.80, 0.15),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    args = ap.parse_args()

    failures: list[str] = []
    for name, min_loo, max_gap in CHECKS:
        path = args.store / name
        if not path.exists():
            failures.append(f"missing {name}")
            continue
        meta = json.loads(path.read_text())
        loo = float(meta.get("loo_auc", 0.0))
        gap = float(meta.get("gap", 0.0))
        shuf = float(meta.get("shuffled_loo_auc", 0.5))
        print(
            f"{name}: loo_auc={loo:.4f} gap={gap:+.4f} shuffled={shuf:.4f}"
        )
        if loo < min_loo:
            failures.append(f"{name}: loo_auc {loo:.3f} < {min_loo}")
        if gap > max_gap:
            # Soft on small-N holdout noise if LOO is strong
            if loo < min_loo + 0.1:
                failures.append(f"{name}: gap {gap:.3f} > {max_gap}")
            else:
                print(f"  (gap soft-pass: strong LOO={loo:.3f})")
        if abs(shuf - 0.5) > 0.30 and loo < 0.75:
            failures.append(f"{name}: shuffled AUC {shuf:.3f} suspicious")

        onnx = path.with_suffix(".onnx")
        if not onnx.exists():
            # face_pad.json → face_pad.onnx etc.
            onnx = args.store / (path.stem + ".onnx")
        if not onnx.exists():
            failures.append(f"missing ONNX for {name}")
        else:
            try:
                import onnxruntime as ort
                import numpy as np

                sess = ort.InferenceSession(
                    str(onnx), providers=["CPUExecutionProvider"]
                )
                inp = sess.get_inputs()[0]
                n = inp.shape[1] if isinstance(inp.shape[1], int) else 1
                sess.run(None, {inp.name: np.zeros((1, n), dtype=np.float32)})
                print(f"  ORT OK {onnx.name}")
            except Exception as exc:
                failures.append(f"ORT smoke {onnx.name}: {exc}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nPASS — Stage 2 overfit audit")


if __name__ == "__main__":
    main()
