#!/usr/bin/env python3
"""Diagnose Driver1 PAD live-vs-training gap and Haar detection failures.

Measure-only. Does not retrain, change thresholds, or modify enrollment data.
Writes phases/driver1_pad_haar_diagnosis.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE = ROOT / "driveauth_store_phase2a"
DATA = ROOT / "data" / "driver1"
DRIVER = "driver1"
OUT = ROOT / "phases" / "driver1_pad_haar_diagnosis.json"
ATTACKS = ("attack_blur", "attack_side", "attack_replay_screen")


def _auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    pos = scores[y_true == 1]
    neg = scores[y_true == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    correct = 0.0
    for p in pos:
        correct += float(np.sum(p > neg)) + 0.5 * float(np.sum(p == neg))
    return correct / (pos.size * neg.size)


def _estimate_pose(cx: float | None, aspect: float | None, face_frac: float | None) -> str:
    if cx is None:
        return "no_detection"
    parts = []
    if cx < 0.25:
        parts.append("left_of_frame")
    elif cx > 0.75:
        parts.append("right_of_frame")
    else:
        parts.append("centered_x")
    if aspect is not None:
        if aspect < 0.65:
            parts.append("tall_narrow")
        elif aspect > 1.35:
            parts.append("wide_short")
        else:
            parts.append("aspect_ok")
    if face_frac is not None:
        if face_frac < 0.12:
            parts.append("too_far")
        elif face_frac > 0.55:
            parts.append("too_close")
        else:
            parts.append("distance_ok")
    return "+".join(parts)


def _failure_reason(
    *,
    n_faces: int,
    face_frac: float | None,
    cx: float | None,
    aspect: float | None,
    brightness: float,
    sharpness: float,
    min_frac: float,
) -> str:
    if n_faces == 0:
        reasons = ["cascade_no_detection"]
        if brightness < 60:
            reasons.append("too_dark")
        elif brightness > 220:
            reasons.append("overexposed")
        if sharpness < 40:
            reasons.append("blur")
        return "+".join(reasons)
    assert face_frac is not None and cx is not None and aspect is not None
    if face_frac < min_frac:
        return f"face_too_small_frac={face_frac:.3f}<{min_frac}"
    if not (0.25 <= cx <= 0.75):
        return f"face_partially_outside_or_offcenter_cx={cx:.3f}"
    if not (0.65 <= aspect <= 1.35):
        return f"excessive_rotation_or_aspect={aspect:.3f}"
    return "unknown_nonfrontal_gate"


def diagnose_pad_parity() -> dict:
    import cv2

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.face_pad_features import (
        FACE_PAD_FEATURE_KEYS,
        extract_face_pad_features,
    )
    from driveauth.stage2_artifacts import FACE_PAD, load_artifact_meta, resolve_bio_artifact

    pad_meta = load_artifact_meta(resolve_bio_artifact(STORE, DRIVER, FACE_PAD))
    train_files = set(pad_meta.get("files") or [])
    excluded = set(pad_meta.get("excluded_fallback_crops") or [])

    # --- Training-style path (DRIVEAUTH_STAGE2_RAW=1, capture_frame + extract) ---
    os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    fm_train = FaceMatcher.load(str(STORE), DRIVER)

    # --- Live path (PAD loaded, capture_and_score) ---
    os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
    fm_live = FaceMatcher.load(str(STORE), DRIVER)

    runtime = {
        "pad_enabled": bool(fm_live.has_pad),
        "pad_source": (fm_live.stage2_info or {}).get("pad_source"),
        "pad_relpath": (fm_live.stage2_info or {}).get("pad_relpath"),
        "pad_threshold": (fm_live.stage2_info or {}).get("pad_threshold"),
        "pad_loo_auc": (fm_live.stage2_info or {}).get("pad_loo_auc"),
        "trained_at": (fm_live.stage2_info or {}).get("trained_at"),
        "calibrator_source": (fm_live.stage2_info or {}).get("calibrator_source"),
        "train_pad_loaded": fm_train.has_pad,  # should be False under STAGE2_RAW
        "onnx_path_resolved": str(
            resolve_bio_artifact(STORE, DRIVER, FACE_PAD).path
        ),
        "legacy_root_exists": (STORE / "face_pad.onnx").is_file(),
        "using_legacy": (fm_live.stage2_info or {}).get("pad_source") == "legacy",
        "ort_providers_pad": (
            list(fm_live._pad._session.get_providers()) if fm_live._pad else None
        ),
        "ort_providers_face": (
            list(fm_live._session.get_providers()) if fm_live._session else None
        ),
    }

    rows = []
    mismatches = []

    splits = [("enroll", 1), ("genuine", 1)] + [(a, 0) for a in ATTACKS]
    for split, label in splits:
        folder = DATA / "face" / split
        for p in sorted(folder.glob("*.jpg")):
            rel = str(p.relative_to(DATA))
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue

            # Training pipeline
            fm_train.inject_bgr(bgr)
            _ = fm_train.capture_frame()
            meta_t = dict(fm_train._last_meta or {})
            crop_t = meta_t.get("bgr")
            used_fb_t = bool(meta_t.get("inject_fallback"))
            if crop_t is None:
                h, w = bgr.shape[:2]
                side = min(h, w)
                y0, x0 = (h - side) // 2, (w - side) // 2
                crop_t = bgr[y0 : y0 + side, x0 : x0 + side]
                used_fb_t = True
                meta_t = {
                    "face_frac": None,
                    "frontal_ok": False,
                    "bgr": crop_t,
                    "inject_fallback": True,
                }
            feats_t = extract_face_pad_features(
                crop_t,
                face_frac=meta_t.get("face_frac"),
                frontal_ok=meta_t.get("frontal_ok"),
            )
            # Score with live PAD head on training features (same ONNX)
            pad_t = (
                float(fm_live._pad.predict_proba(feats_t)) if fm_live._pad else None
            )

            # Live pipeline
            fm_live.inject_bgr(bgr)
            r = fm_live.capture_and_score()
            meta_l = dict(fm_live._last_meta or {})
            crop_l = meta_l.get("bgr")
            used_fb_l = bool(meta_l.get("inject_fallback"))
            feats_l = extract_face_pad_features(
                crop_l if crop_l is not None else crop_t,
                face_frac=meta_l.get("face_frac"),
                frontal_ok=meta_l.get("frontal_ok"),
            )
            pad_l = (
                float(fm_live.last_pad_score)
                if fm_live.last_pad_score is not None
                else None
            )

            crop_t_shape = list(crop_t.shape) if crop_t is not None else None
            crop_l_shape = list(crop_l.shape) if crop_l is not None else None
            feat_max_abs = float(np.max(np.abs(feats_t - feats_l)))
            feat_equal = feat_max_abs < 1e-6
            pad_delta = (
                abs(pad_t - pad_l)
                if pad_t is not None and pad_l is not None
                else None
            )
            crop_equal = (
                crop_t is not None
                and crop_l is not None
                and crop_t.shape == crop_l.shape
                and bool(np.array_equal(crop_t, crop_l))
            )
            meta_equal = (
                meta_t.get("face_frac") == meta_l.get("face_frac")
                and meta_t.get("frontal_ok") == meta_l.get("frontal_ok")
                and used_fb_t == used_fb_l
            )

            row = {
                "file": rel,
                "label": int(label),
                "in_train_set": rel in train_files,
                "excluded_fallback": rel in excluded,
                "train": {
                    "crop_shape": crop_t_shape,
                    "face_frac": meta_t.get("face_frac"),
                    "frontal_ok": meta_t.get("frontal_ok"),
                    "fallback": used_fb_t,
                    "feats": [float(x) for x in feats_t],
                    "pad_score": pad_t,
                },
                "live": {
                    "crop_shape": crop_l_shape,
                    "face_frac": meta_l.get("face_frac"),
                    "frontal_ok": meta_l.get("frontal_ok"),
                    "fallback": used_fb_l,
                    "feats": [float(x) for x in feats_l],
                    "pad_score": pad_l,
                    "calibrated_score": float(r.score) if r.score is not None else None,
                    "pad_reject": bool(fm_live.last_pad_reject),
                },
                "parity": {
                    "crop_equal": crop_equal,
                    "meta_equal": meta_equal,
                    "feat_equal": feat_equal,
                    "feat_max_abs_delta": feat_max_abs,
                    "pad_abs_delta": pad_delta,
                },
            }
            rows.append(row)
            if not (crop_equal and meta_equal and feat_equal and (pad_delta or 0) < 1e-5):
                mismatches.append(
                    {
                        "file": rel,
                        "crop_equal": crop_equal,
                        "meta_equal": meta_equal,
                        "feat_equal": feat_equal,
                        "feat_max_abs_delta": feat_max_abs,
                        "pad_abs_delta": pad_delta,
                        "train_fallback": used_fb_t,
                        "live_fallback": used_fb_l,
                    }
                )

    # AUC slices
    def slice_auc(predicate):
        labs, scs = [], []
        for r in rows:
            if not predicate(r):
                continue
            if r["live"]["pad_score"] is None:
                continue
            labs.append(r["label"])
            scs.append(r["live"]["pad_score"])
        if not labs:
            return None
        return {
            "n": len(labs),
            "n_pos": int(sum(labs)),
            "n_neg": int(len(labs) - sum(labs)),
            "auc": float(_auc(np.array(labs), np.array(scs, dtype=float))),
            "genuine_mean": float(
                np.mean([s for lab, s in zip(labs, scs) if lab == 1])
            )
            if any(lab == 1 for lab in labs)
            else None,
            "attack_mean": float(
                np.mean([s for lab, s in zip(labs, scs) if lab == 0])
            )
            if any(lab == 0 for lab in labs)
            else None,
        }

    thr = float(runtime["pad_threshold"] or 0.39)
    conf = {"tp": 0, "tn": 0, "fp": 0, "fn": 0}
    for r in rows:
        ps = r["live"]["pad_score"]
        if ps is None:
            continue
        pred = ps >= thr
        lab = r["label"]
        if lab == 1 and pred:
            conf["tp"] += 1
        elif lab == 0 and not pred:
            conf["tn"] += 1
        elif lab == 0 and pred:
            conf["fp"] += 1
        else:
            conf["fn"] += 1

    # Compare feat means train-in vs excluded genuines
    def feat_mean(predicate):
        xs = [r["live"]["feats"] for r in rows if predicate(r)]
        if not xs:
            return None
        arr = np.array(xs, dtype=float)
        return {
            k: float(v)
            for k, v in zip(FACE_PAD_FEATURE_KEYS, arr.mean(axis=0))
        }

    return {
        "runtime_config": runtime,
        "pad_meta_summary": {
            "loo_auc": pad_meta.get("loo_auc"),
            "train_auc": pad_meta.get("train_auc"),
            "n_train": pad_meta.get("n"),
            "n_pos": pad_meta.get("n_pos"),
            "n_neg": pad_meta.get("n_neg"),
            "threshold": pad_meta.get("threshold"),
            "exclude_fallback_crops": pad_meta.get("exclude_fallback_crops"),
            "n_excluded": len(excluded),
            "apcer_at_thr": pad_meta.get("apcer_at_thr"),
            "bpcer_at_thr": pad_meta.get("bpcer_at_thr"),
        },
        "feature_keys": list(FACE_PAD_FEATURE_KEYS),
        "parity": {
            "n_samples": len(rows),
            "n_mismatches": len(mismatches),
            "mismatches": mismatches,
            "all_crops_equal": all(r["parity"]["crop_equal"] for r in rows),
            "all_feats_equal": all(r["parity"]["feat_equal"] for r in rows),
            "max_feat_delta": max(r["parity"]["feat_max_abs_delta"] for r in rows)
            if rows
            else 0.0,
            "max_pad_delta": max(
                (r["parity"]["pad_abs_delta"] or 0.0) for r in rows
            )
            if rows
            else 0.0,
        },
        "auc_slices": {
            "all_eval_samples": slice_auc(lambda r: True),
            "train_set_only": slice_auc(lambda r: r["in_train_set"]),
            "excluded_fallback_only": slice_auc(lambda r: r["excluded_fallback"]),
            "haar_ok_only": slice_auc(lambda r: not r["live"]["fallback"]),
            "fallback_only": slice_auc(lambda r: r["live"]["fallback"]),
            "genuine_haar_ok": slice_auc(
                lambda r: r["label"] == 1 and not r["live"]["fallback"]
            ),
            "genuine_fallback": slice_auc(
                lambda r: r["label"] == 1 and r["live"]["fallback"]
            ),
        },
        "confusion_all": conf,
        "feature_means": {
            "train_set": feat_mean(lambda r: r["in_train_set"]),
            "excluded_fallback": feat_mean(lambda r: r["excluded_fallback"]),
            "haar_ok": feat_mean(lambda r: not r["live"]["fallback"]),
            "fallback": feat_mean(lambda r: r["live"]["fallback"]),
        },
        "per_sample": rows,
    }


def diagnose_haar() -> dict:
    import cv2

    from driveauth import config

    min_frac = float(config.FACE_MIN_FRAC)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    fallback_rows = []
    all_rows = []
    production = {"scaleFactor": 1.1, "minNeighbors": 5, "minSize": None}

    splits = ["enroll", "genuine"] + list(ATTACKS)
    images = []
    for split in splits:
        for p in sorted((DATA / "face" / split).glob("*.jpg")):
            images.append((split, p))

    for split, p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5
        )
        n_faces = len(faces)
        face_frac = cx = aspect = face_w = face_h = None
        reason = None
        is_fallback = False
        if n_faces == 0:
            is_fallback = True
            reason = _failure_reason(
                n_faces=0,
                face_frac=None,
                cx=None,
                aspect=None,
                brightness=brightness,
                sharpness=sharpness,
                min_frac=min_frac,
            )
        else:
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            face_w, face_h = int(fw), int(fh)
            face_frac = float(fh / max(h, 1))
            cx = float((x + fw / 2.0) / max(w, 1))
            aspect = float(fw / max(fh, 1))
            if face_frac < min_frac or not (
                0.25 <= cx <= 0.75 and 0.65 <= aspect <= 1.35
            ):
                is_fallback = True
                reason = _failure_reason(
                    n_faces=n_faces,
                    face_frac=face_frac,
                    cx=cx,
                    aspect=aspect,
                    brightness=brightness,
                    sharpness=sharpness,
                    min_frac=min_frac,
                )

        # Fallback crop vs expected Haar crop comparison
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        fallback_crop = bgr[y0 : y0 + side, x0 : x0 + side]
        expected_crop = None
        if n_faces > 0:
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            pad = int(0.15 * fh)
            x0e = max(0, x - pad)
            y0e = max(0, y - pad)
            x1e = min(w, x + fw + pad)
            y1e = min(h, y + fh + pad)
            expected_crop = bgr[y0e:y1e, x0e:x1e]

        row = {
            "filename": p.name,
            "relpath": str(p.relative_to(DATA)),
            "split": split,
            "image_size": [int(w), int(h)],
            "n_haar_boxes": int(n_faces),
            "face_size": [face_w, face_h] if face_w else None,
            "face_frac": face_frac,
            "cx": cx,
            "aspect": aspect,
            "brightness": brightness,
            "blur_laplacian_var": sharpness,
            "estimated_pose": _estimate_pose(cx, aspect, face_frac),
            "detector_confidence": None,  # Haar has no score
            "is_fallback": is_fallback,
            "reason": reason if is_fallback else "haar_ok",
            "fallback_crop_shape": list(fallback_crop.shape),
            "expected_crop_shape": list(expected_crop.shape)
            if expected_crop is not None
            else None,
            "fallback_vs_expected_iou_proxy": None,
        }
        if expected_crop is not None and is_fallback:
            # Rough overlap: how much of expected face bbox center sits in center crop
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            fcx, fcy = x + fw / 2.0, y + fh / 2.0
            in_center = (x0 <= fcx < x0 + side) and (y0 <= fcy < y0 + side)
            face_area = fw * fh
            crop_area = side * side
            row["fallback_vs_expected"] = {
                "face_center_in_center_crop": bool(in_center),
                "face_area_over_crop_area": float(face_area / max(crop_area, 1)),
                "face_frac_of_frame": float(fh / max(h, 1)),
                "note": (
                    "Fallback uses full min-side square; expected uses padded face box. "
                    "Center-crop dilutes the face; honest meta now uses "
                    "face_frac=None + frontal_ok=False (PAD fail-closed)."
                ),
            }
        all_rows.append(row)
        if is_fallback:
            fallback_rows.append(row)

    # Categorize
    cats: dict[str, int] = {}
    for r in fallback_rows:
        key = r["reason"].split("+")[0] if r["reason"] else "unknown"
        # coarsen
        if "cascade_no_detection" in (r["reason"] or ""):
            key = "cascade_no_detection"
            if "blur" in (r["reason"] or ""):
                key = "cascade_no_detection+blur"
            if "too_dark" in (r["reason"] or ""):
                key = "cascade_no_detection+too_dark"
        elif "face_too_small" in (r["reason"] or ""):
            key = "too_far_face_frac"
        elif "offcenter" in (r["reason"] or "") or "outside" in (r["reason"] or ""):
            key = "offcenter_or_partial"
        elif "aspect" in (r["reason"] or "") or "rotation" in (r["reason"] or ""):
            key = "aspect_or_rotation_gate"
        cats[key] = cats.get(key, 0) + 1

    # Sensitivity sweep (temporary; does not change production defaults)
    sweep_cfgs = [
        {"scaleFactor": 1.05, "minNeighbors": 3, "minSize": (30, 30)},
        {"scaleFactor": 1.05, "minNeighbors": 5, "minSize": (30, 30)},
        {"scaleFactor": 1.1, "minNeighbors": 3, "minSize": None},
        {"scaleFactor": 1.1, "minNeighbors": 5, "minSize": None},  # production
        {"scaleFactor": 1.1, "minNeighbors": 5, "minSize": (30, 30)},
        {"scaleFactor": 1.15, "minNeighbors": 5, "minSize": None},
        {"scaleFactor": 1.2, "minNeighbors": 3, "minSize": (20, 20)},
        {"scaleFactor": 1.05, "minNeighbors": 2, "minSize": (20, 20)},
        {"scaleFactor": 1.03, "minNeighbors": 3, "minSize": (20, 20)},
    ]
    # Also test relaxing frontal gates without changing cascade
    gate_variants = [
        {"name": "prod_gates", "min_frac": min_frac, "cx_lo": 0.25, "cx_hi": 0.75, "asp_lo": 0.65, "asp_hi": 1.35},
        {"name": "relax_frac_0.12", "min_frac": 0.12, "cx_lo": 0.25, "cx_hi": 0.75, "asp_lo": 0.65, "asp_hi": 1.35},
        {"name": "relax_cx_0.15_0.85", "min_frac": min_frac, "cx_lo": 0.15, "cx_hi": 0.85, "asp_lo": 0.65, "asp_hi": 1.35},
        {"name": "relax_aspect_0.5_1.5", "min_frac": min_frac, "cx_lo": 0.25, "cx_hi": 0.75, "asp_lo": 0.5, "asp_hi": 1.5},
        {"name": "no_frontal_gates", "min_frac": 0.0, "cx_lo": 0.0, "cx_hi": 1.0, "asp_lo": 0.0, "asp_hi": 99.0},
    ]

    sensitivity = []
    for cfg in sweep_cfgs:
        ok = 0
        cascade_hit = 0
        for split, p in images:
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            kwargs = dict(scaleFactor=cfg["scaleFactor"], minNeighbors=cfg["minNeighbors"])
            if cfg["minSize"]:
                kwargs["minSize"] = cfg["minSize"]
            faces = cascade.detectMultiScale(gray, **kwargs)
            if len(faces) == 0:
                continue
            cascade_hit += 1
            fh_img = bgr.shape[0]
            fw_img = bgr.shape[1]
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            face_frac = fh / max(fh_img, 1)
            cx = (x + fw / 2.0) / max(fw_img, 1)
            aspect = fw / max(fh, 1)
            if face_frac >= min_frac and 0.25 <= cx <= 0.75 and 0.65 <= aspect <= 1.35:
                ok += 1
        n = len(images)
        sensitivity.append(
            {
                **{k: (list(v) if isinstance(v, tuple) else v) for k, v in cfg.items()},
                "cascade_hit_rate": cascade_hit / n,
                "production_gate_pass_rate": ok / n,
                "cascade_hits": cascade_hit,
                "gate_passes": ok,
                "n": n,
                "is_production": (
                    cfg["scaleFactor"] == 1.1
                    and cfg["minNeighbors"] == 5
                    and cfg["minSize"] is None
                ),
            }
        )

    gate_sensitivity = []
    for g in gate_variants:
        ok = 0
        cascade_hit = 0
        for split, p in images:
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
            if len(faces) == 0:
                continue
            cascade_hit += 1
            fh_img = bgr.shape[0]
            fw_img = bgr.shape[1]
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            face_frac = fh / max(fh_img, 1)
            cx = (x + fw / 2.0) / max(fw_img, 1)
            aspect = fw / max(fh, 1)
            if (
                face_frac >= g["min_frac"]
                and g["cx_lo"] <= cx <= g["cx_hi"]
                and g["asp_lo"] <= aspect <= g["asp_hi"]
            ):
                ok += 1
        n = len(images)
        gate_sensitivity.append(
            {
                **g,
                "cascade_hit_rate": cascade_hit / n,
                "gate_pass_rate": ok / n,
                "gate_passes": ok,
                "n": n,
            }
        )

    # Combined best: softer cascade + no frontal gates
    best_combo = {"scaleFactor": 1.05, "minNeighbors": 2, "minSize": (20, 20)}
    ok = cascade_hit = 0
    for split, p in images:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.05,
            minNeighbors=2,
            minSize=(20, 20),
        )
        if len(faces) == 0:
            continue
        cascade_hit += 1
        ok += 1  # no frontal gates
    n = len(images)
    best_combo_result = {
        **{k: (list(v) if isinstance(v, tuple) else v) for k, v in best_combo.items()},
        "gates": "none",
        "cascade_hit_rate": cascade_hit / n,
        "accept_rate": ok / n,
        "n": n,
        "note": "Upper bound if cascade params relaxed AND frontal gates removed",
    }

    return {
        "production_config": {
            **production,
            "face_min_frac": min_frac,
            "frontal_cx": [0.25, 0.75],
            "frontal_aspect": [0.65, 1.35],
            "cascade": "haarcascade_frontalface_default.xml",
        },
        "summary": {
            "n_images": len(all_rows),
            "haar_ok": sum(1 for r in all_rows if not r["is_fallback"]),
            "fallback": len(fallback_rows),
            "detection_rate": sum(1 for r in all_rows if not r["is_fallback"])
            / max(len(all_rows), 1),
        },
        "failure_categories": cats,
        "fallback_images": fallback_rows,
        "all_images": all_rows,
        "parameter_sensitivity": sensitivity,
        "gate_sensitivity": gate_sensitivity,
        "best_combo_upper_bound": best_combo_result,
    }


def main() -> None:
    print("PAD train/live parity + AUC slices...")
    pad = diagnose_pad_parity()
    print(
        f"  parity mismatches={pad['parity']['n_mismatches']} "
        f"max_feat_delta={pad['parity']['max_feat_delta']:.2e} "
        f"train_set_auc={pad['auc_slices']['train_set_only']} "
        f"all_auc={pad['auc_slices']['all_eval_samples']}"
    )
    print("Haar fallback analysis + sensitivity...")
    haar = diagnose_haar()
    print(
        f"  detection_rate={haar['summary']['detection_rate']:.3f} "
        f"fallback={haar['summary']['fallback']} cats={haar['failure_categories']}"
    )

    report = {
        "driver_id": DRIVER,
        "store": str(STORE),
        "data": str(DATA),
        "pad": pad,
        "haar": haar,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
