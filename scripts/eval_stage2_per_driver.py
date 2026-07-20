#!/usr/bin/env python3
"""Honest Stage-2 per-driver evaluation (face / voice / PAD / trust bars).

Writes ``phases/stage2_per_driver_eval.json``. Does not lower thresholds.

Usage:
  python scripts/eval_stage2_per_driver.py --drivers driver1,driver7
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

from driveauth.stage2_artifacts import (  # noqa: E402
    FACE_CALIBRATOR,
    FACE_PAD,
    VOICE_CALIBRATOR,
    load_artifact_meta,
    resolve_bio_artifact,
)

FACE_ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")
VOICE_ATTACKS = ("attack_other_speaker", "attack_replay", "attack_silent", "noisy")


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


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    correct = 0.0
    for p in pos:
        correct += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return correct / (pos.size * neg.size)


def _modality_stats(genuine: list[float], attack: list[float]) -> dict:
    y = np.array([1] * len(genuine) + [0] * len(attack), dtype=np.int32)
    s = np.array(genuine + attack, dtype=np.float64)
    return {
        "n": int(y.size),
        "n_genuine": len(genuine),
        "n_attack": len(attack),
        "genuine_mean": float(np.mean(genuine)) if genuine else None,
        "attack_mean": float(np.mean(attack)) if attack else None,
        "separation": (
            float(np.mean(genuine) - np.mean(attack)) if genuine and attack else None
        ),
        "auc": float(_auc(y, s)) if y.size and genuine and attack else None,
    }


def _score_face_pass(
    store: Path, data: Path, driver_id: str, *, raw: bool
) -> tuple[list[float], list[float], list[int], list[float], bool]:
    """Return genuine, attack scores, pad labels, pad scores, pad_enabled."""
    import cv2

    from driveauth.matchers.face import FaceMatcher

    if raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    else:
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    fm = FaceMatcher.load(str(store), driver_id)
    genuine: list[float] = []
    attack: list[float] = []
    pad_labels: list[int] = []
    pad_scores: list[float] = []

    for p in sorted((data / "face" / "genuine").glob("*.jpg")):
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if fm.last_pad_score is not None:
            pad_labels.append(1)
            pad_scores.append(float(fm.last_pad_score))
        # PAD reject → score None; treat as 0 for ranking honesty
        genuine.append(float(r.score) if r.score is not None else 0.0)

    for split in FACE_ATTACKS:
        for p in sorted((data / "face" / split).glob("*.jpg")):
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            fm.inject_bgr(bgr)
            r = fm.capture_and_score()
            if fm.last_pad_score is not None:
                pad_labels.append(0)
                pad_scores.append(float(fm.last_pad_score))
            attack.append(float(r.score) if r.score is not None else 0.0)

    return genuine, attack, pad_labels, pad_scores, bool(fm.has_pad)


def _score_voice_pass(
    store: Path, data: Path, driver_id: str, *, raw: bool
) -> tuple[list[float], list[float]]:
    from driveauth.matchers.voice import VoiceMatcher

    if raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    else:
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))
    genuine: list[float] = []
    attack: list[float] = []
    for p in sorted((data / "voice" / "genuine").glob("*.wav")):
        r = vm.score(_load_wav(p))
        if r.score is not None:
            genuine.append(float(r.score))
    for split in VOICE_ATTACKS:
        for p in sorted((data / "voice" / split).glob("*.wav")):
            r = vm.score(_load_wav(p))
            if r.score is not None:
                attack.append(float(r.score))
    return genuine, attack


def _pad_block(
    store: Path,
    driver_id: str,
    pad_labels: list[int],
    pad_scores: list[float],
    pad_enabled_runtime: bool,
) -> dict:
    pad_ref = resolve_bio_artifact(store, driver_id, FACE_PAD)
    meta = load_artifact_meta(pad_ref)
    labels = np.array(pad_labels, dtype=np.int32)
    scores = np.array(pad_scores, dtype=np.float64)
    thr = float(meta.get("threshold") or 0.5)
    confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    eval_auc = None
    if labels.size and scores.size:
        pred = scores >= thr
        for lab, pr in zip(labels, pred, strict=False):
            if lab == 1 and pr:
                confusion["tp"] += 1
            elif lab == 0 and not pr:
                confusion["tn"] += 1
            elif lab == 0 and pr:
                confusion["fp"] += 1
            else:
                confusion["fn"] += 1
        eval_auc = float(_auc(labels, scores))
    loo = meta.get("loo_auc")
    try:
        loo_f = float(loo) if loo is not None else None
    except (TypeError, ValueError):
        loo_f = None
    enabled = pad_enabled_runtime and (loo_f is None or loo_f > 0.55)
    return {
        "enabled": enabled,
        "loo_auc": loo_f,
        "threshold": meta.get("threshold"),
        "excluded_fallback": meta.get("excluded_fallback_crops") or [],
        "recommendation": "enable" if enabled else "disable",
        "eval_auc": eval_auc,
        "confusion": confusion,
        "source": pad_ref.source,
        "training_origin": (
            "migrated_copy" if meta.get("migrated_from") else "independent"
        ),
    }


def _trust(voice_mean: float | None, face_mean: float | None, tag: str, bars: dict) -> dict:
    lv, lf = bars["ladder_voice"], bars["ladder_face"]
    v_ok = voice_mean is not None and voice_mean >= lv
    f_ok = face_mean is not None and face_mean >= lf
    parts = [x for x in (voice_mean, face_mean) if x is not None]
    fused = float(np.mean(parts)) if parts else None
    trust_std = bars["trust_std"]
    return {
        "tag": tag,
        "genuine_voice_mean": voice_mean,
        "genuine_face_mean": face_mean,
        "ladder_voice": lv,
        "ladder_face": lf,
        "voice_pass": bool(v_ok),
        "face_pass": bool(f_ok),
        # Ladder early-stops on first modality that clears its bar (OR).
        "ladder_decision": "ACCEPT" if (v_ok or f_ok) else "REJECT",
        "fused_trust": fused,
        "trust_std_bar": trust_std,
        "trust_decision": (
            "ACCEPT" if fused is not None and fused >= trust_std else "REJECT"
        ),
        "note": (
            "ladder_decision uses early-stop OR across voice/face mean scores; "
            "trust_decision uses equal-weight mean of cal means vs TRUST_ACCEPT_STD "
            "(proxy — live path also uses trust_fusion.onnx + risk)."
        ),
    }


def eval_driver(store: Path, data_root: Path, driver_id: str) -> dict:
    data = data_root / driver_id

    raw_fg, raw_fa, _, _, _ = _score_face_pass(store, data, driver_id, raw=True)
    cal_fg, cal_fa, pad_labels, pad_scores, pad_on = _score_face_pass(
        store, data, driver_id, raw=False
    )
    raw_vg, raw_va = _score_voice_pass(store, data, driver_id, raw=True)
    cal_vg, cal_va = _score_voice_pass(store, data, driver_id, raw=False)

    raw_f = _modality_stats(raw_fg, raw_fa)
    cal_f = _modality_stats(cal_fg, cal_fa)
    raw_v = _modality_stats(raw_vg, raw_va)
    cal_v = _modality_stats(cal_vg, cal_va)

    face = {
        "n": cal_f["n"],
        "n_genuine": cal_f["n_genuine"],
        "n_attack": cal_f["n_attack"],
        "raw_genuine_mean": raw_f["genuine_mean"],
        "raw_attack_mean": raw_f["attack_mean"],
        "raw_separation": raw_f["separation"],
        "raw_auc": raw_f["auc"],
        "cal_genuine_mean": cal_f["genuine_mean"],
        "cal_attack_mean": cal_f["attack_mean"],
        "cal_separation": cal_f["separation"],
        "cal_auc": cal_f["auc"],
    }
    voice = {
        "n": cal_v["n"],
        "n_genuine": cal_v["n_genuine"],
        "n_attack": cal_v["n_attack"],
        "raw_genuine_mean": raw_v["genuine_mean"],
        "raw_attack_mean": raw_v["attack_mean"],
        "raw_separation": raw_v["separation"],
        "raw_auc": raw_v["auc"],
        "cal_genuine_mean": cal_v["genuine_mean"],
        "cal_attack_mean": cal_v["attack_mean"],
        "cal_separation": cal_v["separation"],
        "cal_auc": cal_v["auc"],
    }
    pad = _pad_block(store, driver_id, pad_labels, pad_scores, pad_on)

    stock = _trust(
        voice["cal_genuine_mean"],
        face["cal_genuine_mean"],
        "stock",
        {"ladder_voice": 0.72, "ladder_face": 0.70, "trust_std": 0.78},
    )
    demo = _trust(
        voice["cal_genuine_mean"],
        face["cal_genuine_mean"],
        "demo_phase2b",
        {"ladder_voice": 0.58, "ladder_face": 0.36, "trust_std": 0.584},
    )

    vmeta = load_artifact_meta(resolve_bio_artifact(store, driver_id, VOICE_CALIBRATOR))
    fmeta = load_artifact_meta(resolve_bio_artifact(store, driver_id, FACE_CALIBRATOR))
    n_enroll = len(list((data / "voice" / "enroll").glob("*.wav")))

    return {
        "driver_id": driver_id,
        "face": face,
        "voice": voice,
        "pad": pad,
        "trust": {"stock": stock, "demo_phase2b": demo},
        "voice_diagnosis": {
            "n_enroll": n_enroll,
            "n_genuine": voice["n_genuine"],
            "n_attack": voice["n_attack"],
            "raw_genuine_std": float(np.std(raw_vg)) if len(raw_vg) > 1 else None,
            "cal_loo": vmeta.get("loo_auc"),
        },
        "face_pad_meta_loo": pad.get("loo_auc"),
        "face_cal_loo": fmeta.get("loo_auc"),
        "voice_cal_loo": vmeta.get("loo_auc"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", type=Path, default=ROOT / "driveauth_store_phase2a")
    ap.add_argument("--data-root", type=Path, default=ROOT / "data")
    ap.add_argument("--drivers", default="driver1,driver7")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "phases" / "stage2_per_driver_eval.json",
    )
    args = ap.parse_args()
    drivers = [d.strip() for d in args.drivers.split(",") if d.strip()]
    out: dict = {}
    for did in drivers:
        print(f"Evaluating {did} …")
        out[did] = eval_driver(args.store, args.data_root, did)
        t = out[did]["trust"]
        print(
            f"  face cal AUC={out[did]['face'].get('cal_auc')} "
            f"voice cal AUC={out[did]['voice'].get('cal_auc')} "
            f"PAD loo={out[did]['pad'].get('loo_auc')} "
            f"enabled={out[did]['pad'].get('enabled')}"
        )
        print(
            f"  stock ladder={t['stock']['ladder_decision']} "
            f"demo ladder={t['demo_phase2b']['ladder_decision']}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
