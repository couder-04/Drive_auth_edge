#!/usr/bin/env python3
"""Driver1 end-to-end readiness audit. Measure-only; does not change policy.

Writes phases/driver1_e2e_audit.json
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import sys
import time
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE = ROOT / "driveauth_store_phase2a"
DATA = ROOT / "data" / "driver1"
DRIVER = "driver1"
OUT = ROOT / "phases" / "driver1_e2e_audit.json"

FACE_ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")
VOICE_ATTACKS = ("attack_other_speaker", "attack_replay", "attack_silent", "noisy")


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    correct = 0.0
    for p in pos:
        correct += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return correct / (pos.size * neg.size)


def _load_wav(path: Path, sr: int = 16_000) -> tuple[np.ndarray, dict]:
    with wave.open(str(path), "rb") as w:
        nch = w.getnchannels()
        fr = w.getframerate()
        nframes = w.getnframes()
        sw = w.getsampwidth()
        frames = w.readframes(nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if nch == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
        duration = nframes / max(fr, 1)
        clip_frac = float(np.mean(np.abs(audio) >= 0.99)) if audio.size else 0.0
        rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
        silence = rms < 0.01
        if fr != sr:
            ratio = sr / fr
            idx = (np.arange(int(len(audio) * ratio)) / ratio).astype(int)
            idx = np.clip(idx, 0, len(audio) - 1)
            audio = audio[idx]
        meta = {
            "sr": fr,
            "duration_s": duration,
            "clip_frac": clip_frac,
            "rms": rms,
            "silence": silence,
            "sampwidth": sw,
            "channels": nch,
        }
        return audio.astype(np.float32), meta


def phase1_integrity() -> dict:
    from driveauth.integrity import check_driver_store
    from driveauth.stage2_artifacts import resolve_all_bio, stage2_status_for_driver

    refs = resolve_all_bio(STORE, DRIVER)
    status = stage2_status_for_driver(STORE, DRIVER)
    try:
        check = check_driver_store(STORE, DRIVER)
    except Exception as exc:
        check = {"error": str(exc)}
    templates = {
        "face_enc": (STORE / "faces" / f"{DRIVER}.enc").is_file(),
        "voice_enc": (STORE / "voices" / f"{DRIVER}.enc").is_file(),
        "finger_enc": (STORE / "fingers" / f"{DRIVER}.enc").is_file(),
        "behavioral_enc": (STORE / "behavioral" / f"{DRIVER}.enc").is_file(),
        "profile": (STORE / "profiles" / f"{DRIVER}.json").is_file(),
        "consent": (STORE / "consent" / f"{DRIVER}.json").is_file(),
        "ood_face": (STORE / "ood_stats" / f"face_{DRIVER}.npz").is_file(),
        "ood_voice": (STORE / "ood_stats" / f"voice_{DRIVER}.npz").is_file(),
        "ood_finger": (STORE / "ood_stats" / f"finger_{DRIVER}.npz").is_file(),
        "mobilefacenet": (STORE / "mobilefacenet.onnx").is_file()
        or (STORE / "mobilefacenet_int8.onnx").is_file(),
        "risk_gbt": (STORE / "risk_gbt.onnx").is_file(),
        "trust_fusion": (STORE / "trust_fusion.onnx").is_file(),
        "fingernet": (STORE / "fingernet_lite_int8.onnx").is_file(),
    }
    artifacts = {}
    for name, ref in refs.items():
        artifacts[name] = {
            "source": ref.source,
            "path": str(ref.path) if ref.path else None,
            "exists": ref.exists,
            "size_bytes": ref.path.stat().st_size if ref.exists else 0,
        }
    legacy_present = {
        a: (STORE / f"{a}.onnx").is_file()
        for a in ("face_pad", "face_calibrator", "voice_calibrator")
    }
    # Cross-driver isolation: confirm driver1 paths != other drivers' files
    isolation = {}
    for other in ("driver2", "driver3", "driver6", "driver7"):
        for art, ref in refs.items():
            if not ref.exists:
                continue
            other_path = None
            if art.startswith("face") or art == "face_pad" or art == "face_calibrator":
                other_path = STORE / "faces" / other / f"{art}.onnx"
            elif art == "voice_calibrator":
                other_path = STORE / "voices" / other / f"{art}.onnx"
            if other_path and other_path.is_file() and ref.path.resolve() == other_path.resolve():
                isolation[f"{art}_shares_{other}"] = True
    return {
        "stage2_status": status,
        "check_driver": check,
        "templates": templates,
        "artifacts": artifacts,
        "legacy_root_present": legacy_present,
        "using_legacy_for_driver1": any(
            a["source"] == "legacy_shared" for a in artifacts.values()
        ),
        "cross_driver_path_collision": isolation,
        "isolation_ok": len(isolation) == 0
        and all(a["source"] == "per_driver" for a in artifacts.values()),
        "modality_scope": status.get("modality_scope"),
    }


def phase2_enrollment() -> dict:
    import cv2

    face = {}
    # counts
    face["enroll_n"] = len(list((DATA / "face" / "enroll").glob("*.jpg")))
    face["genuine_n"] = len(list((DATA / "face" / "genuine").glob("*.jpg")))
    attack_counts = {}
    for split in FACE_ATTACKS:
        attack_counts[split] = len(list((DATA / "face" / split).glob("*.jpg")))
    face["attack_counts"] = attack_counts
    face["attack_n"] = sum(attack_counts.values())
    face["class_balance_genuine_vs_attack"] = {
        "genuine": face["genuine_n"],
        "attack": face["attack_n"],
        "ratio_g_over_a": face["genuine_n"] / max(face["attack_n"], 1),
    }

    hashes: dict[str, list[str]] = defaultdict(list)
    haar_ok = 0
    haar_fail = 0
    fallback_crops = 0
    blurry = 0
    brightnesses = []
    sharpnesses = []
    face_fracs = []
    aspect_ratios = []
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    all_face = []
    for split in ("enroll", "genuine", *FACE_ATTACKS):
        for p in sorted((DATA / "face" / split).glob("*.jpg")):
            all_face.append((split, p))

    for split, p in all_face:
        data = p.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        hashes[h].append(f"{split}/{p.name}")
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(np.mean(gray))
        sharpnesses.append(lap)
        brightnesses.append(bright)
        if lap < 40.0:
            blurry += 1
        if len(faces) == 0:
            haar_fail += 1
            fallback_crops += 1
        else:
            fh, fw = bgr.shape[0], bgr.shape[1]
            x, y, w, hbox = max(faces, key=lambda r: r[2] * r[3])
            frac = hbox / max(fh, 1)
            aspect = w / max(hbox, 1)
            face_fracs.append(frac)
            aspect_ratios.append(aspect)
            cx = (x + w / 2.0) / max(fw, 1)
            frontal = 0.25 <= cx <= 0.75 and 0.65 <= aspect <= 1.35
            if frac < 0.18 or not frontal:
                haar_fail += 1
                fallback_crops += 1
            else:
                haar_ok += 1

    dups = {k: v for k, v in hashes.items() if len(v) > 1}
    face["duplicates"] = list(dups.values())
    face["duplicate_groups"] = len(dups)
    face["haar_detect_ok"] = haar_ok
    face["haar_fail_or_nonfrontal"] = haar_fail
    face["detection_rate"] = haar_ok / max(haar_ok + haar_fail, 1)
    face["fallback_crop_count"] = fallback_crops
    face["blurry_laplacian_lt_40"] = blurry
    face["sharpness"] = {
        "mean": float(np.mean(sharpnesses)),
        "min": float(np.min(sharpnesses)),
        "max": float(np.max(sharpnesses)),
        "p10": float(np.percentile(sharpnesses, 10)),
    }
    face["brightness"] = {
        "mean": float(np.mean(brightnesses)),
        "min": float(np.min(brightnesses)),
        "max": float(np.max(brightnesses)),
        "std": float(np.std(brightnesses)),
    }
    face["face_frac"] = {
        "n": len(face_fracs),
        "mean": float(np.mean(face_fracs)) if face_fracs else None,
        "min": float(np.min(face_fracs)) if face_fracs else None,
    }
    face["aspect"] = {
        "mean": float(np.mean(aspect_ratios)) if aspect_ratios else None,
        "std": float(np.std(aspect_ratios)) if aspect_ratios else None,
    }
    face["lighting_variation_brightness_std"] = float(np.std(brightnesses))
    face["pose_proxy_aspect_std"] = (
        float(np.std(aspect_ratios)) if aspect_ratios else None
    )

    # Voice
    voice = {"splits": {}}
    durations = []
    srs = []
    clip_n = 0
    silent_n = 0
    for split in ("enroll", "genuine", *VOICE_ATTACKS):
        files = sorted((DATA / "voice" / split).glob("*.wav"))
        voice["splits"][split] = len(files)
        for p in files:
            _, meta = _load_wav(p)
            durations.append(meta["duration_s"])
            srs.append(meta["sr"])
            if meta["clip_frac"] > 0.02:
                clip_n += 1
            if meta["silence"]:
                silent_n += 1
    voice["genuine_n"] = voice["splits"].get("genuine", 0)
    voice["enroll_n"] = voice["splits"].get("enroll", 0)
    voice["attack_n"] = sum(voice["splits"].get(s, 0) for s in VOICE_ATTACKS)
    voice["duration_s"] = {
        "mean": float(np.mean(durations)) if durations else None,
        "min": float(np.min(durations)) if durations else None,
        "max": float(np.max(durations)) if durations else None,
    }
    voice["sample_rates"] = sorted(set(srs))
    voice["sr_consistent"] = len(set(srs)) == 1
    voice["clipping_files"] = clip_n
    voice["silent_files"] = silent_n
    voice["noisy_n"] = voice["splits"].get("noisy", 0)

    # Behavior
    beh = {
        "genuine_n": len(list((DATA / "behavioral" / "genuine").glob("*.csv"))),
        "attack_n": len(list((DATA / "behavioral" / "attack").glob("*.csv"))),
        "template_exists": (STORE / "behavioral" / f"{DRIVER}.enc").is_file(),
        "source": (DATA / "behavioral" / "SOURCE.txt").read_text()[:200]
        if (DATA / "behavioral" / "SOURCE.txt").exists()
        else None,
        "synthetic": True,
    }
    # Finger
    finger = {
        "enroll_n": len(list((DATA / "finger" / "enroll").glob("*.png"))),
        "genuine_n": len(list((DATA / "finger" / "genuine").glob("*.png"))),
        "attack_n": len(
            [
                p
                for p in (DATA / "finger" / "attack").rglob("*.png")
                if p.is_file()
            ]
        ),
        "template_exists": (STORE / "fingers" / f"{DRIVER}.enc").is_file(),
        "fingernet_model": (STORE / "fingernet_lite_int8.onnx").is_file(),
    }
    return {"face": face, "voice": voice, "behavioral": beh, "finger": finger}


def phase3_4_face_voice() -> dict:
    import cv2

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher

    # Face raw
    os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    fm_raw = FaceMatcher.load(str(STORE), DRIVER)
    # Face cal
    os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
    fm = FaceMatcher.load(str(STORE), DRIVER)

    def score_faces(matcher, raw_mode: bool):
        if raw_mode:
            os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
        else:
            os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
        # reload to be safe
        m = FaceMatcher.load(str(STORE), DRIVER)
        genuine = []
        attack = []
        pad_g = []
        pad_a = []
        det = {"haar_ok": 0, "fallback": 0, "pad_reject_g": 0, "pad_reject_a": 0}
        cos_g = []
        cos_a = []
        rows = []
        latencies = []
        for p in sorted((DATA / "face" / "genuine").glob("*.jpg")):
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            m.inject_bgr(bgr)
            t0 = time.perf_counter()
            r = m.capture_and_score()
            latencies.append((time.perf_counter() - t0) * 1000)
            meta = m._last_meta or {}
            if meta.get("inject_fallback"):
                det["fallback"] += 1
            else:
                det["haar_ok"] += 1
            sc = float(r.score) if r.score is not None else 0.0
            genuine.append(sc)
            if m.last_pad_score is not None:
                pad_g.append(float(m.last_pad_score))
            if r.score is None and m.last_pad_reject:
                det["pad_reject_g"] += 1
            # raw cosine via embed
            emb = m.embed_bgr(bgr)
            if emb is not None and m._emb is not None:
                cos_g.append(float(np.dot(m._emb, emb)))
            rows.append(
                {
                    "file": p.name,
                    "label": "genuine",
                    "score": sc,
                    "pad": m.last_pad_score,
                    "fallback": bool(meta.get("inject_fallback")),
                }
            )
        for split in FACE_ATTACKS:
            for p in sorted((DATA / "face" / split).glob("*.jpg")):
                bgr = cv2.imread(str(p))
                if bgr is None:
                    continue
                m.inject_bgr(bgr)
                t0 = time.perf_counter()
                r = m.capture_and_score()
                latencies.append((time.perf_counter() - t0) * 1000)
                meta = m._last_meta or {}
                if meta.get("inject_fallback"):
                    det["fallback"] += 1
                else:
                    det["haar_ok"] += 1
                sc = float(r.score) if r.score is not None else 0.0
                attack.append(sc)
                if m.last_pad_score is not None:
                    pad_a.append(float(m.last_pad_score))
                if r.score is None and m.last_pad_reject:
                    det["pad_reject_a"] += 1
                emb = m.embed_bgr(bgr)
                if emb is not None and m._emb is not None:
                    cos_a.append(float(np.dot(m._emb, emb)))
                rows.append(
                    {
                        "file": f"{split}/{p.name}",
                        "label": "attack",
                        "split": split,
                        "score": sc,
                        "pad": m.last_pad_score,
                        "fallback": bool(meta.get("inject_fallback")),
                    }
                )
        y = np.array([1] * len(genuine) + [0] * len(attack))
        s = np.array(genuine + attack, dtype=float)
        pad_labels = [1] * len(pad_g) + [0] * len(pad_a)
        pad_scores = pad_g + pad_a
        thr = float((m.stage2_info or {}).get("pad_threshold") or 0.39)
        confusion = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
        for lab, ps in zip(pad_labels, pad_scores):
            pred = ps >= thr
            if lab == 1 and pred:
                confusion["tp"] += 1
            elif lab == 0 and not pred:
                confusion["tn"] += 1
            elif lab == 0 and pred:
                confusion["fp"] += 1
            else:
                confusion["fn"] += 1
        return {
            "genuine_mean": float(np.mean(genuine)) if genuine else None,
            "attack_mean": float(np.mean(attack)) if attack else None,
            "genuine_std": float(np.std(genuine)) if genuine else None,
            "attack_std": float(np.std(attack)) if attack else None,
            "separation": float(np.mean(genuine) - np.mean(attack))
            if genuine and attack
            else None,
            "auc": float(_auc(y, s)) if genuine and attack else None,
            "n_genuine": len(genuine),
            "n_attack": len(attack),
            "cosine_genuine_mean": float(np.mean(cos_g)) if cos_g else None,
            "cosine_attack_mean": float(np.mean(cos_a)) if cos_a else None,
            "cosine_auc": float(
                _auc(
                    np.array([1] * len(cos_g) + [0] * len(cos_a)),
                    np.array(cos_g + cos_a, dtype=float),
                )
            )
            if cos_g and cos_a
            else None,
            "detection": det,
            "pad": {
                "enabled": bool(m.has_pad),
                "threshold": thr,
                "stage2_info": m.stage2_info,
                "genuine_mean": float(np.mean(pad_g)) if pad_g else None,
                "attack_mean": float(np.mean(pad_a)) if pad_a else None,
                "auc": float(_auc(np.array(pad_labels), np.array(pad_scores)))
                if pad_scores
                else None,
                "confusion": confusion,
                "false_accepts_fp": confusion["fp"],
                "false_rejects_fn": confusion["fn"],
            },
            "latency_ms": {
                "mean": float(np.mean(latencies)) if latencies else None,
                "p95": float(np.percentile(latencies, 95)) if latencies else None,
                "max": float(np.max(latencies)) if latencies else None,
                "n": len(latencies),
            },
            "per_file": rows,
        }

    face_raw = score_faces(fm_raw, True)
    face_cal = score_faces(fm, False)

    # Voice
    def score_voices(raw_mode: bool):
        if raw_mode:
            os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
        else:
            os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
        vm = VoiceMatcher.load(str(STORE / "enroll"), DRIVER, store_dir=str(STORE))
        genuine = []
        attack = []
        rows = []
        latencies = []
        by_split = defaultdict(list)
        for p in sorted((DATA / "voice" / "genuine").glob("*.wav")):
            audio, _ = _load_wav(p)
            t0 = time.perf_counter()
            r = vm.score(audio)
            latencies.append((time.perf_counter() - t0) * 1000)
            if r.score is not None:
                genuine.append(float(r.score))
                rows.append({"file": p.name, "label": "genuine", "score": float(r.score)})
        for split in VOICE_ATTACKS:
            for p in sorted((DATA / "voice" / split).glob("*.wav")):
                audio, _ = _load_wav(p)
                t0 = time.perf_counter()
                r = vm.score(audio)
                latencies.append((time.perf_counter() - t0) * 1000)
                if r.score is not None:
                    attack.append(float(r.score))
                    by_split[split].append(float(r.score))
                    rows.append(
                        {
                            "file": f"{split}/{p.name}",
                            "label": "attack",
                            "split": split,
                            "score": float(r.score),
                        }
                    )
        y = np.array([1] * len(genuine) + [0] * len(attack))
        s = np.array(genuine + attack, dtype=float)
        return {
            "genuine_mean": float(np.mean(genuine)) if genuine else None,
            "attack_mean": float(np.mean(attack)) if attack else None,
            "genuine_std": float(np.std(genuine)) if genuine else None,
            "separation": float(np.mean(genuine) - np.mean(attack))
            if genuine and attack
            else None,
            "auc": float(_auc(y, s)) if genuine and attack else None,
            "n_genuine": len(genuine),
            "n_attack": len(attack),
            "attack_by_split_mean": {k: float(np.mean(v)) for k, v in by_split.items()},
            "calibrator_source": getattr(vm, "_stage2_info", None)
            or {
                "note": "see VoiceMatcher load logs",
            },
            "latency_ms": {
                "mean": float(np.mean(latencies)) if latencies else None,
                "p95": float(np.percentile(latencies, 95)) if latencies else None,
                "max": float(np.max(latencies)) if latencies else None,
                "n": len(latencies),
            },
            "per_file": rows,
            "above_stock_0_72": int(sum(1 for g in genuine if g >= 0.72)),
            "above_demo_0_58": int(sum(1 for g in genuine if g >= 0.58)),
            "frac_above_stock": float(np.mean([g >= 0.72 for g in genuine]))
            if genuine
            else None,
            "frac_above_demo": float(np.mean([g >= 0.58 for g in genuine]))
            if genuine
            else None,
        }

    voice_raw = score_voices(True)
    voice_cal = score_voices(False)

    # LOO from meta
    from driveauth.stage2_artifacts import (
        FACE_CALIBRATOR,
        FACE_PAD,
        VOICE_CALIBRATOR,
        load_artifact_meta,
        resolve_bio_artifact,
    )

    pad_meta = load_artifact_meta(resolve_bio_artifact(STORE, DRIVER, FACE_PAD))
    face_cal_meta = load_artifact_meta(
        resolve_bio_artifact(STORE, DRIVER, FACE_CALIBRATOR)
    )
    voice_cal_meta = load_artifact_meta(
        resolve_bio_artifact(STORE, DRIVER, VOICE_CALIBRATOR)
    )

    return {
        "face_raw": {k: v for k, v in face_raw.items() if k != "per_file"},
        "face_cal": {k: v for k, v in face_cal.items() if k != "per_file"},
        "face_cal_per_file_summary": {
            "n_genuine_ge_0_70": sum(
                1
                for r in face_cal["per_file"]
                if r["label"] == "genuine" and r["score"] >= 0.70
            ),
            "n_genuine_ge_0_36": sum(
                1
                for r in face_cal["per_file"]
                if r["label"] == "genuine" and r["score"] >= 0.36
            ),
            "n_genuine": sum(1 for r in face_cal["per_file"] if r["label"] == "genuine"),
            "n_attack_ge_0_70": sum(
                1
                for r in face_cal["per_file"]
                if r["label"] == "attack" and r["score"] >= 0.70
            ),
            "n_attack_ge_0_36": sum(
                1
                for r in face_cal["per_file"]
                if r["label"] == "attack" and r["score"] >= 0.36
            ),
        },
        "voice_raw": {k: v for k, v in voice_raw.items() if k != "per_file"},
        "voice_cal": {k: v for k, v in voice_cal.items() if k != "per_file"},
        "loo": {
            "face_pad": pad_meta.get("loo_auc"),
            "face_calibrator": face_cal_meta.get("loo_auc"),
            "voice_calibrator": voice_cal_meta.get("loo_auc"),
            "face_pad_apcer": pad_meta.get("apcer_at_thr"),
            "face_pad_bpcer": pad_meta.get("bpcer_at_thr"),
            "pad_disabled": pad_meta.get("pad_disabled"),
        },
        "face_cal_full_rows": face_cal["per_file"],
        "voice_cal_full_rows": voice_cal["per_file"],
    }


def phase5_6_finger_behavior() -> dict:
    from driveauth.matchers.behavioral import BehavioralMonitor
    from driveauth.matchers.finger import FingerMatcher
    from driveauth.stage2_artifacts import stage2_status_for_driver

    fm = FingerMatcher.load(str(STORE), DRIVER)
    scope = stage2_status_for_driver(STORE, DRIVER).get("modality_scope") or {}
    finger = {
        "template_loaded": fm._template is not None,
        "session_loaded": fm._session is not None,
        "ready": fm._template is not None and fm._session is not None,
        "finger_enrolled": bool(scope.get("finger_enrolled")),
        "modality_scope": scope,
        "note": scope.get("scope_note")
        or (
            "No fingers/driver1.enc — 2-modality scope (voice + face); "
            "not an enrollment defect. See docs/security-assumptions.md."
        ),
    }
    # Attempt score (will fail without socket/template)
    t0 = time.perf_counter()
    r = fm.capture_and_score()
    finger["capture_score"] = r.score
    finger["capture_available"] = getattr(r, "available", None)
    finger["capture_confident"] = r.confident
    finger["latency_ms"] = (time.perf_counter() - t0) * 1000

    from driveauth.matchers.behavioral import BEHAVIORAL_FEATURE_KEYS

    bm = BehavioralMonitor.load(str(STORE), DRIVER)
    beh = {
        "available": bm.available,
        "has_profile": bm._profile is not None,
        "score_mode": bm._score_mode,
        "arch": bm._arch,
        "profile_dim": int(np.asarray(bm._profile).size) if bm._profile is not None else 0,
        "model_loaded": bm._session is not None,
    }
    genuine_scores = []
    attack_scores = []
    latencies = []

    def _score_csv(path: Path) -> float | None:
        import csv

        bm._buf.clear()
        bm._score = None
        with path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                sensor = {k: float(row.get(k, 0) or 0) for k in BEHAVIORAL_FEATURE_KEYS}
                bm.update(sensor)
        t0 = time.perf_counter()
        out = bm.get_score()
        latencies.append((time.perf_counter() - t0) * 1000)
        return float(out.score) if out.score is not None else None

    try:
        for p in sorted((DATA / "behavioral" / "genuine").glob("*.csv")):
            sc = _score_csv(p)
            if sc is not None:
                genuine_scores.append(sc)
        for p in sorted((DATA / "behavioral" / "attack").glob("*.csv")):
            sc = _score_csv(p)
            if sc is not None:
                attack_scores.append(sc)
    except Exception as exc:
        beh["error"] = str(exc)

    beh["genuine_scores_n"] = len(genuine_scores)
    beh["attack_scores_n"] = len(attack_scores)
    if genuine_scores:
        beh["genuine_mean"] = float(np.mean(genuine_scores))
        beh["genuine_std"] = float(np.std(genuine_scores))
    if attack_scores:
        beh["attack_mean"] = float(np.mean(attack_scores))
        beh["attack_std"] = float(np.std(attack_scores))
    if genuine_scores and attack_scores:
        beh["separation"] = float(np.mean(genuine_scores) - np.mean(attack_scores))
        beh["auc"] = float(
            _auc(
                np.array([1] * len(genuine_scores) + [0] * len(attack_scores)),
                np.array(genuine_scores + attack_scores, dtype=float),
            )
        )
    if latencies:
        beh["latency_ms_mean"] = float(np.mean(latencies))
    beh["synthetic_data"] = True
    beh["health"] = (
        "provisional_synthetic"
        if (STORE / "behavioral" / f"{DRIVER}.enc").is_file()
        else "missing_template"
    )
    return {"finger": finger, "behavioral": beh}


def phase7_10_decision() -> dict:
    """Run live DriveAuth decisions under stock and demo thresholds."""
    import cv2

    from driveauth.api import DriveAuth
    from driveauth.matchers.voice import VoiceMatcher

    results = {"stock": {}, "demo": {}}

    def run_policy(tag: str, env_overrides: dict | None = None) -> dict:
        # Clear ladder/trust overrides then apply
        keys = [
            "DRIVEAUTH_TRUST_ACCEPT_MICRO",
            "DRIVEAUTH_TRUST_ACCEPT_STD",
            "DRIVEAUTH_TRUST_ACCEPT_HIGH",
            "DRIVEAUTH_TRUST_REJECT",
            "DRIVEAUTH_LADDER_ACCEPT_VOICE",
            "DRIVEAUTH_LADDER_ACCEPT_FACE",
            "DRIVEAUTH_LADDER_ACCEPT_FINGER",
            "DRIVEAUTH_LADDER_ACCEPT",
        ]
        for k in keys:
            os.environ.pop(k, None)
        if env_overrides:
            for k, v in env_overrides.items():
                os.environ[k] = str(v)
        # Force config reload
        import importlib

        import driveauth.config as cfg

        importlib.reload(cfg)

        da = DriveAuth.load(str(STORE), DRIVER)
        cases = []

        # Genuine voice samples (first 5)
        for p in sorted((DATA / "voice" / "genuine").glob("*.wav"))[:5]:
            audio, _ = _load_wav(p)
            # inject matching face if available
            face_p = DATA / "face" / "genuine" / p.name.replace(".wav", ".jpg").replace(
                "genuine_", "genuine_"
            )
            # map genuine_01.wav -> genuine_01.jpg
            face_p = DATA / "face" / "genuine" / (p.stem + ".jpg")
            if face_p.exists() and da._engine._m.face is not None:
                bgr = cv2.imread(str(face_p))
                if bgr is not None and hasattr(da._engine._m.face, "inject_bgr"):
                    da._engine._m.face.inject_bgr(bgr)
            t0 = time.perf_counter()
            res = da.authenticate(
                audio_np=audio,
                amount=500.0,
                beneficiary="self",
                beneficiary_known=True,
                audit=False,
            )
            lat = (time.perf_counter() - t0) * 1000
            cases.append(
                {
                    "case": f"genuine_voice+face:{p.name}",
                    **_case_fields(res),
                    "latency_ms": lat,
                }
            )

        def _append(case: str, res) -> None:
            cases.append({"case": case, **_case_fields(res)})

        # Impostor voice (other speaker)
        for p in sorted((DATA / "voice" / "attack_other_speaker").glob("*.wav"))[:3]:
            audio, _ = _load_wav(p)
            # use ood face if available
            ood = sorted((DATA / "ood" / "face").glob("*.jpg"))
            if ood and da._engine._m.face is not None:
                bgr = cv2.imread(str(ood[0]))
                if bgr is not None and hasattr(da._engine._m.face, "inject_bgr"):
                    da._engine._m.face.inject_bgr(bgr)
            res = da.authenticate(
                audio_np=audio, amount=500.0, beneficiary_known=True, audit=False
            )
            _append(f"impostor_voice+ood_face:{p.name}", res)

        # Spoof face (screen) + genuine voice
        gen_v = sorted((DATA / "voice" / "genuine").glob("*.wav"))[0]
        audio, _ = _load_wav(gen_v)
        for p in sorted((DATA / "face" / "attack_replay_screen").glob("*.jpg"))[:3]:
            bgr = cv2.imread(str(p))
            if bgr is not None and da._engine._m.face is not None and hasattr(
                da._engine._m.face, "inject_bgr"
            ):
                da._engine._m.face.inject_bgr(bgr)
            res = da.authenticate(
                audio_np=audio, amount=500.0, beneficiary_known=True, audit=False
            )
            _append(f"spoof_face_screen+genuine_voice:{p.name}", res)

        # Replay voice + genuine face
        gen_f = sorted((DATA / "face" / "genuine").glob("*.jpg"))[0]
        bgr = cv2.imread(str(gen_f))
        if bgr is not None and da._engine._m.face is not None and hasattr(
            da._engine._m.face, "inject_bgr"
        ):
            da._engine._m.face.inject_bgr(bgr)
        for p in sorted((DATA / "voice" / "attack_replay").glob("*.wav"))[:3]:
            audio, _ = _load_wav(p)
            res = da.authenticate(
                audio_np=audio, amount=500.0, beneficiary_known=True, audit=False
            )
            _append(f"replay_voice+genuine_face:{p.name}", res)

        # Side profile attack
        for p in sorted((DATA / "face" / "attack_side").glob("*.jpg"))[:3]:
            audio, _ = _load_wav(gen_v)
            bgr = cv2.imread(str(p))
            if bgr is not None and da._engine._m.face is not None and hasattr(
                da._engine._m.face, "inject_bgr"
            ):
                da._engine._m.face.inject_bgr(bgr)
            res = da.authenticate(
                audio_np=audio, amount=500.0, beneficiary_known=True, audit=False
            )
            _append(f"side_face+genuine_voice:{p.name}", res)

        # Silent voice
        for p in sorted((DATA / "voice" / "attack_silent").glob("*.wav"))[:2]:
            audio, _ = _load_wav(p)
            if da._engine._m.face is not None and hasattr(da._engine._m.face, "inject_bgr"):
                da._engine._m.face.inject_bgr(cv2.imread(str(gen_f)))
            res = da.authenticate(
                audio_np=audio, amount=500.0, beneficiary_known=True, audit=False
            )
            _append(f"silent_voice+genuine_face:{p.name}", res)

        # Thresholds used
        bars = {
            "ladder_voice": cfg.LADDER_ACCEPT_VOICE,
            "ladder_face": cfg.LADDER_ACCEPT_FACE,
            "ladder_finger": cfg.LADDER_ACCEPT_FINGER,
            "trust_std": cfg.TRUST_ACCEPT_STD,
            "trust_micro": cfg.TRUST_ACCEPT_MICRO,
            "trust_high": cfg.TRUST_ACCEPT_HIGH,
            "trust_reject": cfg.TRUST_REJECT,
        }

        # Margin analysis on genuine means from modality matchers alone
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
        vm = VoiceMatcher.load(str(STORE / "enroll"), DRIVER, store_dir=str(STORE))
        v_scores = []
        for p in sorted((DATA / "voice" / "genuine").glob("*.wav")):
            a, _ = _load_wav(p)
            rr = vm.score(a)
            if rr.score is not None:
                v_scores.append(float(rr.score))
        from driveauth.matchers.face import FaceMatcher

        fm = FaceMatcher.load(str(STORE), DRIVER)
        f_scores = []
        for p in sorted((DATA / "face" / "genuine").glob("*.jpg")):
            bb = cv2.imread(str(p))
            if bb is None:
                continue
            fm.inject_bgr(bb)
            rr = fm.capture_and_score()
            f_scores.append(float(rr.score) if rr.score is not None else 0.0)

        v_mean = float(np.mean(v_scores)) if v_scores else None
        f_mean = float(np.mean(f_scores)) if f_scores else None
        margins = {
            "voice_mean": v_mean,
            "face_mean": f_mean,
            "voice_margin_to_ladder": (v_mean - bars["ladder_voice"])
            if v_mean is not None
            else None,
            "face_margin_to_ladder": (f_mean - bars["ladder_face"])
            if f_mean is not None
            else None,
            "fused_equal_weight": (
                (v_mean + f_mean) / 2.0 if v_mean is not None and f_mean is not None else None
            ),
        }
        if margins["fused_equal_weight"] is not None:
            margins["trust_margin_to_std"] = (
                margins["fused_equal_weight"] - bars["trust_std"]
            )

        accept_n = sum(1 for c in cases if c["decision"] == "ACCEPT")
        reject_n = sum(1 for c in cases if c["decision"] == "REJECT")
        other = [
            c["decision"]
            for c in cases
            if c["decision"] not in ("ACCEPT", "REJECT")
        ]
        return {
            "tag": tag,
            "bars": bars,
            "margins": margins,
            "cases": cases,
            "summary": {
                "n": len(cases),
                "accept": accept_n,
                "reject": reject_n,
                "other": other,
                "genuine_accept_rate": sum(
                    1
                    for c in cases
                    if c["case"].startswith("genuine") and c["decision"] == "ACCEPT"
                )
                / max(
                    sum(1 for c in cases if c["case"].startswith("genuine")),
                    1,
                ),
                "attack_reject_rate": sum(
                    1
                    for c in cases
                    if not c["case"].startswith("genuine") and c["decision"] == "REJECT"
                )
                / max(
                    sum(1 for c in cases if not c["case"].startswith("genuine")),
                    1,
                ),
            },
        }

    results["stock"] = run_policy("stock", None)
    demo = {
        "DRIVEAUTH_TRUST_ACCEPT_MICRO": "0.554",
        "DRIVEAUTH_TRUST_ACCEPT_STD": "0.584",
        "DRIVEAUTH_TRUST_ACCEPT_HIGH": "0.614",
        "DRIVEAUTH_TRUST_REJECT": "0.419",
        "DRIVEAUTH_LADDER_ACCEPT_VOICE": "0.58",
        "DRIVEAUTH_LADDER_ACCEPT_FACE": "0.36",
        "DRIVEAUTH_LADDER_ACCEPT_FINGER": "0.7",
    }
    results["demo"] = run_policy("demo_phase2b", demo)
    # restore stock
    for k in list(demo.keys()):
        os.environ.pop(k, None)
    import importlib

    import driveauth.config as cfg

    importlib.reload(cfg)
    return results


def _mod_score(res, name: str):
    mods = getattr(res, "modality_scores", None) or {}
    if isinstance(mods, dict):
        v = mods.get(name)
        if v is None:
            return None
        if hasattr(v, "score"):
            return v.score
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            return v.get("score")
    return None


def _case_fields(res) -> dict:
    return {
        "decision": str(res.decision.value if hasattr(res.decision, "value") else res.decision),
        "trust": res.trust_score,
        "risk": res.risk_score,
        "confidence": res.confidence_score,
        "voice": _mod_score(res, "voice"),
        "face": _mod_score(res, "face"),
        "finger": _mod_score(res, "finger"),
        "behavior": _mod_score(res, "behavioral") or _mod_score(res, "behavior"),
        "reasons": list(res.explanations or [])[:8],
        "policy_rule": res.policy_rule,
        "tier": res.tier,
        "modality_scores": {
            k: (v.get("score") if isinstance(v, dict) else getattr(v, "score", v))
            for k, v in (res.modality_scores or {}).items()
        },
    }


def phase12_perf(face_voice: dict, decisions: dict) -> dict:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "face_latency_ms": face_voice["face_cal"]["latency_ms"],
        "voice_latency_ms": face_voice["voice_cal"]["latency_ms"],
        "auth_latencies_stock": [
            c.get("latency_ms")
            for c in decisions["stock"]["cases"]
            if c.get("latency_ms") is not None
        ],
        "auth_latency_mean_stock": float(
            np.mean(
                [
                    c["latency_ms"]
                    for c in decisions["stock"]["cases"]
                    if c.get("latency_ms") is not None
                ]
            )
        )
        if any(c.get("latency_ms") for c in decisions["stock"]["cases"])
        else None,
        "max_rss_mb": ru.ru_maxrss / (1024 * 1024)
        if sys.platform == "darwin"
        else ru.ru_maxrss / 1024,
        "hailo": "not_configured",
    }


def phase13_security(integrity: dict, face_voice: dict, decisions: dict) -> dict:
    pad = face_voice["face_cal"]["pad"]
    stock_cases = decisions["stock"]["cases"]
    demo_cases = decisions["demo"]["cases"]

    def rate(cases, prefix, want):
        subset = [c for c in cases if c["case"].startswith(prefix)]
        if not subset:
            return None
        return sum(1 for c in subset if c["decision"] == want) / len(subset)

    return {
        "per_driver_isolation_ok": integrity["isolation_ok"],
        "using_legacy_fallback": integrity["using_legacy_for_driver1"],
        "legacy_files_still_on_disk": integrity["legacy_root_present"],
        "pad_enabled": pad["enabled"],
        "pad_eval_auc": pad["auc"],
        "pad_false_accepts": pad["false_accepts_fp"],
        "stock_genuine_accept_rate": rate(stock_cases, "genuine", "ACCEPT"),
        "stock_impostor_reject_rate": rate(stock_cases, "impostor", "REJECT"),
        "stock_spoof_face_reject_rate": rate(stock_cases, "spoof_face", "REJECT"),
        "stock_replay_voice_reject_rate": rate(stock_cases, "replay_voice", "REJECT"),
        "stock_side_reject_rate": rate(stock_cases, "side_face", "REJECT"),
        "demo_genuine_accept_rate": rate(demo_cases, "genuine", "ACCEPT"),
        "demo_impostor_reject_rate": rate(demo_cases, "impostor", "REJECT"),
        "demo_spoof_face_reject_rate": rate(demo_cases, "spoof_face", "REJECT"),
        "demo_replay_voice_reject_rate": rate(demo_cases, "replay_voice", "REJECT"),
        "threshold_override_detection": "demo bars documented in phase2b_suggested.env; runtime WARNING expected",
        "finger_mismatch": "N/A — no finger template; stage3 unavailable",
        "deepfake": "not_in_dataset",
    }


def main() -> None:
    os.chdir(ROOT)
    # load secrets if present
    secrets = ROOT / "secrets.env"
    if secrets.exists():
        for line in secrets.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    report: dict = {"driver_id": DRIVER, "store": str(STORE), "data": str(DATA)}
    print("Phase 1 integrity...")
    report["phase1_integrity"] = phase1_integrity()
    print("Phase 2 enrollment...")
    report["phase2_enrollment"] = phase2_enrollment()
    print("Phase 3-4 face/voice...")
    report["phase3_4"] = phase3_4_face_voice()
    print("Phase 5-6 finger/behavior...")
    report["phase5_6"] = phase5_6_finger_behavior()
    print("Phase 7-10 decisions...")
    report["phase7_10"] = phase7_10_decision()
    print("Phase 12 perf...")
    report["phase12_perf"] = phase12_perf(report["phase3_4"], report["phase7_10"])
    print("Phase 13 security...")
    report["phase13_security"] = phase13_security(
        report["phase1_integrity"], report["phase3_4"], report["phase7_10"]
    )

    # Drop huge per-file from top-level copy in summary size — keep them
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {OUT}")
    # compact stdout summary
    p34 = report["phase3_4"]
    print(
        "FACE cal:",
        p34["face_cal"]["genuine_mean"],
        p34["face_cal"]["attack_mean"],
        "AUC",
        p34["face_cal"]["auc"],
    )
    print(
        "VOICE cal:",
        p34["voice_cal"]["genuine_mean"],
        p34["voice_cal"]["attack_mean"],
        "AUC",
        p34["voice_cal"]["auc"],
    )
    print("STOCK:", report["phase7_10"]["stock"]["summary"])
    print("DEMO:", report["phase7_10"]["demo"]["summary"])
    print("FINGER template:", report["phase1_integrity"]["templates"]["finger_enc"])
    print("Isolation OK:", report["phase1_integrity"]["isolation_ok"])


if __name__ == "__main__":
    main()
