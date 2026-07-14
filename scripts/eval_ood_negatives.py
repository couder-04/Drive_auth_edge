#!/usr/bin/env python3
"""Stage 1 — evaluate OOD negatives against enrolled Phase 2a templates.

Scores ``data/<driver>/ood/{face,voice}`` with ECAPA + MobileFaceNet and
checks live ``OODDetector`` flags. Finger OOD stays synth until HW arrives.

Trust fusion may use Stage-2 logreg when trust_fusion.onnx is present.

Usage:
  python scripts/eval_ood_negatives.py --store ./driveauth_store_phase2a
  python scripts/eval_ood_negatives.py --store ./driveauth_store_phase2a --json
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_wav(path: Path, sr: int = 16_000) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
        if w.getframerate() != sr:
            ratio = sr / w.getframerate()
            idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        return audio.astype(np.float32)


def _summarize(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0}
    a = np.asarray(scores, dtype=np.float64)
    return {
        "n": int(a.size),
        "mean": round(float(a.mean()), 4),
        "p50": round(float(np.percentile(a, 50)), 4),
        "p90": round(float(np.percentile(a, 90)), 4),
        "max": round(float(a.max()), 4),
        "min": round(float(a.min()), 4),
    }


def _eval_voice(store: Path, data: Path, driver_id: str, match_ceil: float) -> dict:
    from driveauth.matchers.voice import VoiceMatcher
    from driveauth.ood_detector import OODDetector

    ood = OODDetector.load(str(store), driver_id)
    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))
    if not vm.ready:
        return {"error": "VoiceMatcher not ready — run phase2a_setup + enroll"}

    wavs = sorted((data / "ood" / "voice").glob("*.wav"))
    # Skip empty stub WAVs left by failed TTS runs
    wavs = [p for p in wavs if p.stat().st_size > 1000]
    scores: list[float] = []
    flagged = 0
    embedded = 0
    details: list[dict] = []
    for p in wavs:
        audio = _load_wav(p)
        res = vm.score(audio)
        if res.score is None or res.embedding is None:
            details.append({"file": p.name, "score": None, "ood": None, "ok": False})
            continue
        embedded += 1
        is_ood, dist, missing = ood.voice.is_ood(res.embedding)
        low_match = float(res.score) <= match_ceil
        ok = is_ood or low_match
        if is_ood:
            flagged += 1
        scores.append(float(res.score))
        details.append(
            {
                "file": p.name,
                "score": round(float(res.score), 4),
                "ood": bool(is_ood),
                "dist": round(float(dist), 4),
                "baseline_missing": bool(missing),
                "ok": ok,
            }
        )
    return {
        "modality": "voice",
        "source": "macOS say TTS (non-enrolled identity)",
        "n_files": len(wavs),
        "n_embedded": embedded,
        "n_ood_flagged": flagged,
        "ood_flag_rate": round(flagged / embedded, 4) if embedded else 0.0,
        "rejected_as_negative": sum(1 for d in details if d.get("ok")),
        "reject_rate": (
            round(sum(1 for d in details if d.get("ok")) / embedded, 4)
            if embedded
            else 0.0
        ),
        "match_score": _summarize(scores),
        "match_ceil": match_ceil,
        "details": details,
    }


def _eval_face(store: Path, data: Path, driver_id: str, match_ceil: float) -> dict:
    import cv2  # type: ignore

    from driveauth.matchers.face import FaceMatcher
    from driveauth.ood_detector import OODDetector

    ood = OODDetector.load(str(store), driver_id)
    fm = FaceMatcher.load(str(store), driver_id)
    if not fm.ready:
        return {"error": "FaceMatcher not ready — run phase2a_setup + enroll"}

    images = sorted(
        [
            * (data / "ood" / "face").glob("*.jpg"),
            * (data / "ood" / "face").glob("*.jpeg"),
            * (data / "ood" / "face").glob("*.png"),
        ]
    )
    scores: list[float] = []
    flagged = 0
    embedded = 0
    details: list[dict] = []
    for p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            details.append({"file": p.name, "score": None, "ood": None, "ok": False})
            continue
        emb = fm.embed_bgr(bgr)
        if emb is None or fm._emb is None:
            details.append({"file": p.name, "score": None, "ood": None, "ok": False})
            continue
        embedded += 1
        sim = float(np.clip(float(np.dot(fm._emb, emb)), 0.0, 1.0))
        is_ood, dist, missing = ood.face.is_ood(emb)
        low_match = sim <= match_ceil
        ok = is_ood or low_match
        if is_ood:
            flagged += 1
        scores.append(sim)
        details.append(
            {
                "file": p.name,
                "score": round(sim, 4),
                "ood": bool(is_ood),
                "dist": round(float(dist), 4),
                "baseline_missing": bool(missing),
                "ok": ok,
            }
        )
    return {
        "modality": "face",
        "source": "other-identity stills (non-enrolled)",
        "n_files": len(images),
        "n_embedded": embedded,
        "n_ood_flagged": flagged,
        "ood_flag_rate": round(flagged / embedded, 4) if embedded else 0.0,
        "rejected_as_negative": sum(1 for d in details if d.get("ok")),
        "reject_rate": (
            round(sum(1 for d in details if d.get("ok")) / embedded, 4)
            if embedded
            else 0.0
        ),
        "match_score": _summarize(scores),
        "match_ceil": match_ceil,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Stage-1 OOD negatives")
    parser.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "driver1")
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument(
        "--match-ceil",
        type=float,
        default=0.55,
        help="Treat match score ≤ this as rejected OOD (alongside detector flags)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "phases" / "phase2a_ood_eval.json",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    args = parser.parse_args()

    report = {
        "store": str(args.store),
        "data": str(args.data),
        "driver_id": args.driver_id,
        "trust_fusion": (
            "logreg"
            if (args.store / "trust_fusion.onnx").exists()
            else "static (no trust_fusion.onnx)"
        ),
        "finger_ood": "synth only — HW pending; not scored here",
        "voice": _eval_voice(args.store, args.data, args.driver_id, args.match_ceil),
        "face": _eval_face(args.store, args.data, args.driver_id, args.match_ceil),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for key in ("voice", "face"):
            block = report[key]
            if "error" in block:
                print(f"{key}: ERROR — {block['error']}")
                continue
            print(
                f"{key}: embedded={block['n_embedded']}/{block['n_files']}  "
                f"ood_flag_rate={block['ood_flag_rate']}  "
                f"reject_rate={block['reject_rate']}  "
                f"match_mean={block['match_score'].get('mean')}  "
                f"match_max={block['match_score'].get('max')}"
            )
        print(f"trust_fusion: {report['trust_fusion']}")
        print(f"Wrote {args.out}")

    # Soft pass: both modalities have samples and reject mostly as negatives
    voice_ok = (
        "error" not in report["voice"]
        and report["voice"].get("n_embedded", 0) >= 3
        and report["voice"].get("reject_rate", 0) >= 0.8
    )
    face_ok = (
        "error" not in report["face"]
        and report["face"].get("n_embedded", 0) >= 5
        and report["face"].get("reject_rate", 0) >= 0.6
    )
    return 0 if voice_ok and face_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
