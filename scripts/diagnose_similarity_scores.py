#!/usr/bin/env python3
"""Rigorous face/voice similarity diagnostic across enrolled drivers.

Reports:
  - LOO self-similarity of enroll samples vs stored templates
  - Cross-driver impostor scores (parth↔pranjal etc.)
  - Auto-generated blur / silent attack scores when possible
  - Quality-gate pass rates
  - Separation (genuine_mean − impostor_mean) and stock-bar clearance

Usage:
  python scripts/diagnose_similarity_scores.py
  python scripts/diagnose_similarity_scores.py --drivers parth,pranjal --out phases/similarity_diag.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth import config  # noqa: E402
from driveauth.improved_auth import (  # noqa: E402
    auto_generate_face_blur,
    auto_generate_voice_silent,
    sync_genuine_from_enroll,
)
from driveauth.quality_gate import score_face, score_voice  # noqa: E402


def _load_wav(path: Path, sr: int = 16_000) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
        if w.getframerate() != sr:
            ratio = sr / float(w.getframerate())
            idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        return audio.astype(np.float32)


def _summarize(scores: list[float]) -> dict:
    if not scores:
        return {"n": 0}
    arr = np.asarray(scores, dtype=np.float64)
    return {
        "n": int(arr.size),
        "mean": round(float(arr.mean()), 4),
        "p10": round(float(np.percentile(arr, 10)), 4),
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p90": round(float(np.percentile(arr, 90)), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
    }


def _list_images(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    out: list[Path] = []
    for pat in ("*.jpg", "*.jpeg", "*.png"):
        out.extend(sorted(folder.glob(pat)))
    return out


def _list_wavs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.wav"))


def _score_face_paths(fm, paths: list[Path]) -> tuple[list[float], dict]:
    import cv2

    scores: list[float] = []
    meta = {
        "haar_ok": 0,
        "scored": 0,
        "pad_reject": 0,
        "none": 0,
        "quality_ok": 0,
    }
    for p in paths:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fm.inject_bgr(bgr)
        frame = fm.capture_frame()
        last = getattr(fm, "_last_meta", {}) or {}
        if last.get("inject_fallback"):
            pass
        else:
            meta["haar_ok"] += 1
        if frame is not None:
            ok, _q, _n = score_face(
                frame,
                face_frac=last.get("face_frac"),
                frontal_ok=last.get("frontal_ok"),
            )
            if ok:
                meta["quality_ok"] += 1
        r = fm.capture_and_score()
        if r.score is None:
            if getattr(fm, "last_pad_reject", False):
                meta["pad_reject"] += 1
            else:
                meta["none"] += 1
            scores.append(0.0)
        else:
            meta["scored"] += 1
            scores.append(float(r.score))
    return scores, meta


def _score_voice_paths(vm, paths: list[Path]) -> tuple[list[float], dict]:
    scores: list[float] = []
    meta = {"scored": 0, "none": 0, "quality_ok": 0}
    for p in paths:
        audio = _load_wav(p)
        ok, _q, _n = score_voice(audio)
        if ok:
            meta["quality_ok"] += 1
        r = vm.score(audio)
        if r.score is None:
            meta["none"] += 1
            scores.append(0.0)
        else:
            meta["scored"] += 1
            scores.append(float(r.score))
    return scores, meta


def _eval_driver(store: Path, data_root: Path, driver_id: str, *, raw: bool) -> dict:
    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher
    from driveauth.stage2_artifacts import stage2_status_for_driver

    if raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    else:
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    data = data_root / driver_id
    sync_genuine_from_enroll(data_root, driver_id)
    try:
        auto_generate_face_blur(data_root, driver_id, n=5)
    except Exception as exc:
        blur_err = str(exc)
    else:
        blur_err = None
    try:
        auto_generate_voice_silent(data_root, driver_id, n=5)
    except Exception as exc:
        silent_err = str(exc)
    else:
        silent_err = None

    fm = FaceMatcher.load(str(store), driver_id)
    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))

    face_enroll = _list_images(data / "face" / "enroll")
    face_genuine = _list_images(data / "face" / "genuine") or face_enroll
    face_blur = _list_images(data / "face" / "attack_blur")
    face_side = _list_images(data / "face" / "attack_side")
    face_screen = _list_images(data / "face" / "attack_replay_screen")

    voice_enroll = _list_wavs(data / "voice" / "enroll")
    voice_genuine = _list_wavs(data / "voice" / "genuine") or voice_enroll
    voice_silent = _list_wavs(data / "voice" / "attack_silent")
    voice_replay = _list_wavs(data / "voice" / "attack_replay")
    voice_other = _list_wavs(data / "voice" / "attack_other_speaker")
    voice_noisy = _list_wavs(data / "voice" / "noisy")

    face_g_scores, face_g_meta = (
        _score_face_paths(fm, face_genuine) if fm.ready else ([], {"error": "not_ready"})
    )
    face_a_scores: list[float] = []
    face_by: dict[str, dict] = {}
    for name, paths in (
        ("attack_blur", face_blur),
        ("attack_side", face_side),
        ("attack_replay_screen", face_screen),
    ):
        if not paths or not fm.ready:
            continue
        sc, meta = _score_face_paths(fm, paths)
        face_by[name] = {"scores": _summarize(sc), "meta": meta}
        face_a_scores.extend(sc)

    voice_g_scores, voice_g_meta = (
        _score_voice_paths(vm, voice_genuine) if vm.ready else ([], {"error": "not_ready"})
    )
    voice_a_scores: list[float] = []
    voice_by: dict[str, dict] = {}
    for name, paths in (
        ("attack_silent", voice_silent),
        ("attack_replay", voice_replay),
        ("attack_other_speaker", voice_other),
        ("noisy", voice_noisy),
    ):
        if not paths or not vm.ready:
            continue
        sc, meta = _score_voice_paths(vm, paths)
        voice_by[name] = {"scores": _summarize(sc), "meta": meta}
        voice_a_scores.extend(sc)

    face_sep = (
        float(np.mean(face_g_scores) - np.mean(face_a_scores))
        if face_g_scores and face_a_scores
        else None
    )
    voice_sep = (
        float(np.mean(voice_g_scores) - np.mean(voice_a_scores))
        if voice_g_scores and voice_a_scores
        else None
    )

    return {
        "driver_id": driver_id,
        "raw": raw,
        "ready": {"face": fm.ready, "voice": vm.ready},
        "stage2": stage2_status_for_driver(store, driver_id),
        "face": {
            "genuine": _summarize(face_g_scores),
            "attack": _summarize(face_a_scores),
            "by_class": face_by,
            "meta_genuine": face_g_meta,
            "separation": None if face_sep is None else round(face_sep, 4),
            "stock_bar": config.LADDER_ACCEPT_FACE,
            "pct_ge_stock": (
                round(
                    float(np.mean(np.asarray(face_g_scores) >= config.LADDER_ACCEPT_FACE)),
                    4,
                )
                if face_g_scores
                else None
            ),
            "blur_err": blur_err,
            "n_enroll": len(face_enroll),
        },
        "voice": {
            "genuine": _summarize(voice_g_scores),
            "attack": _summarize(voice_a_scores),
            "by_class": voice_by,
            "meta_genuine": voice_g_meta,
            "separation": None if voice_sep is None else round(voice_sep, 4),
            "stock_bar": config.LADDER_ACCEPT_VOICE,
            "pct_ge_stock": (
                round(
                    float(
                        np.mean(np.asarray(voice_g_scores) >= config.LADDER_ACCEPT_VOICE)
                    ),
                    4,
                )
                if voice_g_scores
                else None
            ),
            "silent_err": silent_err,
            "n_enroll": len(voice_enroll),
        },
    }


def _cross_driver(store: Path, data_root: Path, drivers: list[str], *, raw: bool) -> dict:
    """Score each driver's enroll samples against every other driver's template."""
    import cv2

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher

    if raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    else:
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    out: dict[str, dict] = {"face": {}, "voice": {}}
    for claim in drivers:
        fm = FaceMatcher.load(str(store), claim)
        vm = VoiceMatcher.load(str(store / "enroll"), claim, store_dir=str(store))
        for probe in drivers:
            face_paths = _list_images(data_root / probe / "face" / "enroll")
            voice_paths = _list_wavs(data_root / probe / "voice" / "enroll")
            key = f"{probe}_vs_{claim}"
            if fm.ready and face_paths:
                sc, _ = _score_face_paths(fm, face_paths)
                out["face"][key] = _summarize(sc)
            if vm.ready and voice_paths:
                sc, _ = _score_voice_paths(vm, voice_paths)
                out["voice"][key] = _summarize(sc)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--drivers", default="parth,pranjal")
    ap.add_argument("--raw", action="store_true", help="Disable Stage-2 heads")
    ap.add_argument("--out", default=str(ROOT / "phases" / "similarity_diag.json"))
    args = ap.parse_args()

    store = Path(args.store)
    data_root = Path(args.data)
    drivers = [d.strip() for d in args.drivers.split(",") if d.strip()]

    report = {
        "store": str(store),
        "raw": bool(args.raw),
        "stock_bars": {
            "voice": config.LADDER_ACCEPT_VOICE,
            "face": config.LADDER_ACCEPT_FACE,
            "finger": config.LADDER_ACCEPT_FINGER,
        },
        "drivers": {},
        "cross_driver": {},
        "issues": [],
    }

    for did in drivers:
        print(f"=== evaluating {did} (raw={args.raw}) ===", flush=True)
        report["drivers"][did] = _eval_driver(store, data_root, did, raw=args.raw)

    print("=== cross-driver impostors ===", flush=True)
    report["cross_driver"] = _cross_driver(store, data_root, drivers, raw=args.raw)

    # Issue heuristics
    for did, block in report["drivers"].items():
        face = block.get("face") or {}
        voice = block.get("voice") or {}
        if face.get("separation") is not None and face["separation"] < 0.05:
            report["issues"].append(
                f"{did} face: poor separation {face['separation']} (genuine≈attack)"
            )
        if voice.get("separation") is not None and voice["separation"] < 0.1:
            report["issues"].append(
                f"{did} voice: poor separation {voice['separation']}"
            )
        if (face.get("pct_ge_stock") or 0) < 0.2 and (face.get("genuine") or {}).get("n", 0) > 0:
            report["issues"].append(
                f"{did} face: only {face.get('pct_ge_stock')} of genuines ≥ stock "
                f"{face.get('stock_bar')} (mean={face.get('genuine', {}).get('mean')})"
            )
        if (voice.get("pct_ge_stock") or 0) < 0.2 and (voice.get("genuine") or {}).get("n", 0) > 0:
            report["issues"].append(
                f"{did} voice: only {voice.get('pct_ge_stock')} of genuines ≥ stock "
                f"{voice.get('stock_bar')} (mean={voice.get('genuine', {}).get('mean')})"
            )
        st = block.get("stage2") or {}
        arts = (st.get("artifacts") or {})
        # PAD is the critical Stage-2 face head; calibrators need diverse
        # attack classes and should not be treated as blocking when absent.
        if not (arts.get("face_pad") or {}).get("present"):
            report["issues"].append(f"{did} stage2 missing: face_pad")

    # Cross-driver: self should beat other
    for mod in ("face", "voice"):
        pairs = report["cross_driver"].get(mod) or {}
        for did in drivers:
            self_key = f"{did}_vs_{did}"
            self_mean = (pairs.get(self_key) or {}).get("mean")
            if self_mean is None:
                continue
            for other in drivers:
                if other == did:
                    continue
                other_key = f"{other}_vs_{did}"
                other_mean = (pairs.get(other_key) or {}).get("mean")
                if other_mean is None:
                    continue
                if float(other_mean) >= float(self_mean) - 0.02:
                    report["issues"].append(
                        f"{mod} cross: impostor {other_key} mean={other_mean} "
                        f"≥ self {self_key} mean={self_mean}"
                    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    if report["issues"]:
        print(f"ISSUES ({len(report['issues'])}):")
        for i in report["issues"]:
            print(f"  - {i}")
        sys.exit(2)


if __name__ == "__main__":
    main()
