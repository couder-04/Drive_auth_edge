#!/usr/bin/env python3
"""Proxy fairness audit: face quality-gate pass rates by brightness bin.

This is NOT a demographic fairness study — it bins enroll/capture images by
mean grayscale brightness as a lighting proxy. See docs/fairness-validation-protocol.md
for the full study design (skin tone + lighting requires consented field data).

Usage::

    python scripts/analyze_fairness.py --data-root ./data --driver driver1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _brightness(path: Path) -> float | None:
    try:
        import cv2
    except ImportError:
        return None
    bgr = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if bgr is None:
        return None
    return float(bgr.mean())


def analyze(data_root: Path, driver_id: str) -> dict:
    from driveauth.matchers.face import assess_face_framing

    face_dir = data_root / driver_id / "face" / "enroll"
    if not face_dir.is_dir():
        return {"driver_id": driver_id, "error": "no enroll face dir", "bins": []}

    bins = {
        "dark": {"n": 0, "pass": 0, "brightness": []},
        "mid": {"n": 0, "pass": 0, "brightness": []},
        "bright": {"n": 0, "pass": 0, "brightness": []},
    }
    for img_path in sorted(face_dir.glob("*.*")):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        try:
            import cv2

            bgr = cv2.imread(str(img_path))
            if bgr is None:
                continue
            bright = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).mean())
        except Exception:
            continue
        if bright < 80:
            key = "dark"
        elif bright > 160:
            key = "bright"
        else:
            key = "mid"
        ok = bool(assess_face_framing(bgr).get("ok"))
        bins[key]["n"] += 1
        bins[key]["pass"] += int(ok)
        bins[key]["brightness"].append(round(bright, 1))

    rows = []
    for name, b in bins.items():
        rate = (b["pass"] / b["n"]) if b["n"] else None
        rows.append(
            {
                "bin": name,
                "count": b["n"],
                "gate_pass": b["pass"],
                "pass_rate": round(rate, 3) if rate is not None else None,
                "brightness_samples": b["brightness"][:10],
            }
        )
    return {
        "driver_id": driver_id,
        "data_dir": str(face_dir),
        "note": "lighting proxy only — not skin-tone fairness",
        "bins": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Face quality-gate pass rates by brightness")
    ap.add_argument("--data-root", type=Path, default=Path("./data"))
    ap.add_argument("--driver", default="driver1")
    ap.add_argument("--out", type=Path, help="Write JSON report")
    args = ap.parse_args()

    report = analyze(args.data_root.expanduser().resolve(), args.driver)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
