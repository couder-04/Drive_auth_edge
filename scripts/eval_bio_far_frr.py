#!/usr/bin/env python3
"""Stage 2 — FAR/FRR eval for voice/face (per-attack-class + EER).

Writes phases/phase2a_bio_baseline.json or phases/phase2b_bio_eval.json.

Usage:
  # Freeze 2a path (ignore Stage-2 heads even if present):
  python scripts/eval_bio_far_frr.py --tag baseline --raw \\
      --out phases/phase2a_bio_baseline.json

  # Stage 2 path (PAD + calibrators when wired):
  python scripts/eval_bio_far_frr.py --tag phase2b \\
      --baseline phases/phase2a_bio_baseline.json \\
      --out phases/phase2b_bio_eval.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._bio_train_common import (  # noqa: E402
    eer_metrics,
    far_frr,
    load_wav,
    summarize,
)

VOICE_ATTACKS = ("attack_replay", "attack_silent", "attack_other_speaker")
FACE_ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")


def _modality_report(genuine: list[float], attack: list[float], by_class: dict) -> dict:
    out = {
        "genuine": summarize(genuine),
        "attack": summarize(attack),
        "metrics": eer_metrics(genuine, attack),
        "by_class": {},
    }
    for name, scores in by_class.items():
        m = eer_metrics(genuine, scores) if genuine and scores else {}
        out["by_class"][name] = {
            "scores": summarize(scores),
            "metrics": m,
            "far_at_eer_thr": (
                round(
                    far_frr(genuine, scores, float(out["metrics"].get("eer_thr", 0.5)))[
                        0
                    ],
                    4,
                )
                if genuine and scores and out["metrics"]
                else None
            ),
        }
    return out


def _beats(baseline: dict | None, current: dict) -> dict:
    if not baseline:
        return {"compared": False}
    result = {"compared": True, "voice": {}, "face": {}}
    for mod in ("voice", "face"):
        b = (baseline.get(mod) or {}).get("metrics") or {}
        c = (current.get(mod) or {}).get("metrics") or {}
        b_eer = b.get("eer")
        c_eer = c.get("eer")
        b_far = b.get("eer_far")
        c_far = c.get("eer_far")
        improved_eer = (
            b_eer is not None and c_eer is not None and float(c_eer) < float(b_eer) - 1e-9
        )
        improved_far = (
            b_far is not None and c_far is not None and float(c_far) < float(b_far) - 1e-9
        )
        # Face PAD: attack mean of admitted-or-zero scores lower is also a win
        b_att = ((baseline.get(mod) or {}).get("attack") or {}).get("mean")
        c_att = ((current.get(mod) or {}).get("attack") or {}).get("mean")
        improved_att = (
            b_att is not None
            and c_att is not None
            and float(c_att) < float(b_att) - 1e-9
        )
        pad = (current.get(mod) or {}).get("pad_attack_reject_rate")
        result[mod] = {
            "baseline_eer": b_eer,
            "current_eer": c_eer,
            "improved_eer": improved_eer,
            "improved_far_at_eer": improved_far,
            "improved_attack_mean": improved_att,
            "pad_attack_reject_rate": pad,
            "beats": bool(improved_eer or improved_far or improved_att or (pad or 0) > 0.5),
        }
    result["beats_2a"] = bool(result["voice"].get("beats") or result["face"].get("beats"))
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    ap.add_argument("--data", default=str(ROOT / "data" / "driver1"))
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--tag", default="eval")
    ap.add_argument(
        "--raw",
        action="store_true",
        help="Disable Stage-2 heads (voice calibrator / face PAD / face calibrator)",
    )
    ap.add_argument("--baseline", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"

    store = Path(args.store)
    data = Path(args.data)

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher

    vm = VoiceMatcher.load(str(store / "enroll"), args.driver_id, store_dir=str(store))
    fm = FaceMatcher.load(str(store), args.driver_id)
    if not vm.ready:
        raise SystemExit("VoiceMatcher not ready")
    if not fm.ready:
        raise SystemExit("FaceMatcher not ready")

    voice_genuine: list[float] = []
    voice_by: dict[str, list[float]] = {k: [] for k in VOICE_ATTACKS}
    for p in sorted((data / "voice" / "genuine").glob("*.wav")):
        r = vm.score(load_wav(p))
        if r.score is not None:
            voice_genuine.append(float(r.score))
    for split in VOICE_ATTACKS:
        for p in sorted((data / "voice" / split).glob("*.wav")):
            r = vm.score(load_wav(p))
            # Missing/low-confidence counts as 0 for FAR (rejected)
            s = float(r.score) if r.score is not None else 0.0
            voice_by[split].append(s)
    voice_attack = [s for xs in voice_by.values() for s in xs]

    import cv2

    face_genuine: list[float] = []
    face_by: dict[str, list[float]] = {k: [] for k in FACE_ATTACKS}
    pad_reject_attack = 0
    pad_reject_genuine = 0
    n_face_attack = 0
    n_face_genuine = 0

    for p in sorted((data / "face" / "genuine").glob("*.jpg")):
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        n_face_genuine += 1
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if r.score is None:
            pad_reject_genuine += 1
            face_genuine.append(0.0)
        else:
            face_genuine.append(float(r.score))

    for split in FACE_ATTACKS:
        for p in sorted((data / "face" / split).glob("*.jpg")):
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            n_face_attack += 1
            fm.inject_bgr(bgr)
            r = fm.capture_and_score()
            if r.score is None:
                pad_reject_attack += 1
                face_by[split].append(0.0)
            else:
                face_by[split].append(float(r.score))
    face_attack = [s for xs in face_by.values() for s in xs]

    report = {
        "tag": args.tag,
        "store": str(store),
        "raw": bool(args.raw),
        "voice": _modality_report(voice_genuine, voice_attack, voice_by),
        "face": _modality_report(face_genuine, face_attack, face_by),
    }
    report["face"]["pad_attack_reject_rate"] = (
        round(pad_reject_attack / max(n_face_attack, 1), 4) if n_face_attack else None
    )
    report["face"]["pad_genuine_reject_rate"] = (
        round(pad_reject_genuine / max(n_face_genuine, 1), 4)
        if n_face_genuine
        else None
    )
    report["face"]["n_scored_attack"] = n_face_attack
    report["face"]["n_scored_genuine"] = n_face_genuine

    baseline = None
    if args.baseline:
        bp = Path(args.baseline)
        if bp.exists():
            baseline = json.loads(bp.read_text())
    report["vs_baseline"] = _beats(baseline, report)

    out = Path(args.out) if args.out else ROOT / "phases" / f"bio_eval_{args.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    if report["vs_baseline"].get("compared"):
        print(f"beats_2a={report['vs_baseline'].get('beats_2a')}")


if __name__ == "__main__":
    main()
