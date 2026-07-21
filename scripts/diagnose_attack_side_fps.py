#!/usr/bin/env python3
"""Diagnose PAD false positives on driver1 attack_side (measure-only).

Writes phases/driver1_attack_side_fp_diagnosis.json
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE = ROOT / "driveauth_store_phase2a"
DATA = ROOT / "data" / "driver1" / "face"
DRIVER = "driver1"
OUT = ROOT / "phases" / "driver1_attack_side_fp_diagnosis.json"
SPLITS = ("enroll", "genuine", "attack_blur", "attack_side", "attack_replay_screen")


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if obj is None or isinstance(obj, str):
        return obj
    return str(obj)


def summarize_image(p: Path) -> dict:
    import cv2

    st = p.stat()
    img = cv2.imread(str(p))
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bright = float(gray.mean())
    sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    corners = np.concatenate(
        [
            gray[:40, :40].ravel(),
            gray[:40, -40:].ravel(),
            gray[-40:, :40].ravel(),
            gray[-40:, -40:].ravel(),
        ]
    )
    center = gray[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4]
    return {
        "file": str(p.relative_to(DATA)),
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "mtime_epoch": st.st_mtime,
        "bytes": st.st_size,
        "sha1_12": hashlib.sha1(p.read_bytes()).hexdigest()[:12],
        "wh": [int(w), int(h)],
        "brightness": round(bright, 2),
        "sharpness": round(sharp, 2),
        "corner_bright": round(float(corners.mean()), 2),
        "center_bright": round(float(center.mean()), 2),
        "corner_minus_center": round(float(corners.mean() - center.mean()), 2),
    }


def score_one(fm, p: Path) -> dict:
    import cv2

    from driveauth.matchers.face import assess_face_framing
    from driveauth.matchers.face_pad_features import (
        FACE_PAD_FEATURE_KEYS,
        extract_face_pad_features,
    )

    img = cv2.imread(str(p))
    framing = assess_face_framing(img)
    fm.inject_bgr(img)
    result = fm.capture_and_score()
    meta = dict(fm._last_meta or {})
    face_frac = meta.get("face_frac")
    frontal_ok = meta.get("frontal_ok")
    inject = bool(meta.get("inject_fallback"))
    box = meta.get("box")
    if box is not None:
        x, y, bw, bh = [int(t) for t in box]
        crop = img[y : y + bh, x : x + bw]
    else:
        h, w = img.shape[:2]
        side = min(h, w)
        y0, x0 = (h - side) // 2, (w - side) // 2
        crop = img[y0 : y0 + side, x0 : x0 + side]
    feats = extract_face_pad_features(
        crop, face_frac=face_frac, frontal_ok=frontal_ok
    )
    return {
        "score": None if result.score is None else float(result.score),
        "confident": bool(result.confident),
        "available": bool(result.available),
        "pad_proba": None
        if fm.last_pad_score is None
        else float(fm.last_pad_score),
        "pad_reject": bool(fm.last_pad_reject),
        "face_frac": None if face_frac is None else float(face_frac),
        "frontal_ok": None if frontal_ok is None else bool(frontal_ok),
        "inject_fallback": inject,
        "box": None if box is None else [int(x) for x in box],
        "framing_ok": bool(framing.get("ok")),
        "framing_reason": framing.get("reason"),
        "framing_face_frac": framing.get("face_frac"),
        "framing_frontal_ok": framing.get("frontal_ok"),
        "feats": {k: float(v) for k, v in zip(FACE_PAD_FEATURE_KEYS, feats)},
        "feat_vec": [float(v) for v in feats],
    }


def check_synth_provenance() -> dict:
    """Re-run synth_side/synth_blur from enroll and compare to on-disk attacks."""
    import cv2

    from scripts.capture_own_face import synth_blur, synth_side

    enroll = sorted((DATA / "enroll").glob("*.jpg"))
    tmp = Path(tempfile.mkdtemp(prefix="side_synth_"))
    side_rows = []
    blur_rows = []
    for i, src in enumerate(enroll[:8], start=1):
        sign = 1.0 if i % 2 else -1.0
        dest = tmp / f"side_{i:02d}.jpg"
        synth_side(src, dest, yaw_sign=sign)
        actual = DATA / "attack_side" / f"side_{i:02d}.jpg"
        a = cv2.imread(str(actual))
        b = cv2.imread(str(dest))
        row = {
            "file": f"attack_side/side_{i:02d}.jpg",
            "enroll_src": src.name,
            "yaw_sign": sign,
            "exists": actual.exists(),
        }
        if a is None or b is None:
            row["status"] = "read_fail"
        elif a.shape != b.shape:
            row["status"] = "shape_mismatch"
            row["actual_shape"] = list(a.shape)
            row["regen_shape"] = list(b.shape)
        else:
            mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
            maxdiff = int(np.max(np.abs(a.astype(np.int16) - b.astype(np.int16))))
            row.update(
                {
                    "status": "ok",
                    "identical_pixels": bool(np.array_equal(a, b)),
                    "mse": mse,
                    "maxdiff": maxdiff,
                    "sha_actual": hashlib.sha1(actual.read_bytes()).hexdigest()[:12],
                    "sha_regen": hashlib.sha1(dest.read_bytes()).hexdigest()[:12],
                }
            )
        side_rows.append(row)

        bdest = tmp / f"blur_{i:02d}.jpg"
        synth_blur(src, bdest)
        bactual = DATA / "attack_blur" / f"blur_{i:02d}.jpg"
        ba = cv2.imread(str(bactual))
        bb = cv2.imread(str(bdest))
        brow = {
            "file": f"attack_blur/blur_{i:02d}.jpg",
            "enroll_src": src.name,
            "exists": bactual.exists(),
        }
        if ba is None or bb is None or ba.shape != bb.shape:
            brow["status"] = "mismatch"
        else:
            brow.update(
                {
                    "status": "ok",
                    "mse": float(
                        np.mean((ba.astype(np.float32) - bb.astype(np.float32)) ** 2)
                    ),
                    "maxdiff": int(
                        np.max(np.abs(ba.astype(np.int16) - bb.astype(np.int16)))
                    ),
                }
            )
        blur_rows.append(brow)

    side_mses = [r["mse"] for r in side_rows if "mse" in r]
    blur_mses = [r["mse"] for r in blur_rows if "mse" in r]
    return {
        "side": side_rows,
        "blur": blur_rows,
        "side_mean_mse": float(np.mean(side_mses)) if side_mses else None,
        "blur_mean_mse": float(np.mean(blur_mses)) if blur_mses else None,
        "side_looks_synth": bool(side_mses) and float(np.mean(side_mses)) < 5.0,
        "blur_looks_synth": bool(blur_mses) and float(np.mean(blur_mses)) < 5.0,
        "note": (
            "mse≈0 means on-disk attack_* matches synth_* from enroll "
            "(JPEG round-trip may leave tiny mse)."
        ),
    }


def split_summary(rows: list[dict], split: str) -> dict:
    rs = [r for r in rows if r["split"] == split]
    if not rs:
        return {"n": 0}
    ff = [r["face_frac"] for r in rs if r["face_frac"] is not None]
    haar_ok = [r for r in rs if not r["inject_fallback"]]
    return {
        "n": len(rs),
        "resolutions": sorted({tuple(r["wh"]) for r in rs}),
        "mtime_min": min(r["mtime"] for r in rs),
        "mtime_max": max(r["mtime"] for r in rs),
        "brightness_mean": float(np.mean([r["brightness"] for r in rs])),
        "brightness_std": float(np.std([r["brightness"] for r in rs])),
        "brightness_min": float(min(r["brightness"] for r in rs)),
        "brightness_max": float(max(r["brightness"] for r in rs)),
        "sharpness_mean": float(np.mean([r["sharpness"] for r in rs])),
        "sharpness_std": float(np.std([r["sharpness"] for r in rs])),
        "sharpness_min": float(min(r["sharpness"] for r in rs)),
        "sharpness_max": float(max(r["sharpness"] for r in rs)),
        "corner_minus_center_mean": float(
            np.mean([r["corner_minus_center"] for r in rs])
        ),
        "bytes_mean": float(np.mean([r["bytes"] for r in rs])),
        "haar_ok": len(haar_ok),
        "fallback": len(rs) - len(haar_ok),
        "face_frac_haar_ok": {
            "n": len(haar_ok),
            "values": [r["face_frac"] for r in haar_ok],
            "mean": float(np.mean([r["face_frac"] for r in haar_ok]))
            if haar_ok
            else None,
            "std": float(np.std([r["face_frac"] for r in haar_ok])) if haar_ok else None,
            "min": float(min(r["face_frac"] for r in haar_ok)) if haar_ok else None,
            "max": float(max(r["face_frac"] for r in haar_ok)) if haar_ok else None,
            "frontal_ok_true": sum(1 for r in haar_ok if r["frontal_ok"] is True),
            "frontal_ok_false": sum(1 for r in haar_ok if r["frontal_ok"] is False),
        },
        "face_frac_all_nonnull": {
            "n": len(ff),
            "mean": float(np.mean(ff)) if ff else None,
            "min": float(min(ff)) if ff else None,
            "max": float(max(ff)) if ff else None,
        },
    }


def main() -> None:
    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.face_pad_features import FACE_PAD_FEATURE_KEYS

    os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)
    fm = FaceMatcher.load(str(STORE), DRIVER)
    thr = float((fm.stage2_info or {}).get("pad_threshold") or fm._pad_threshold or 0.0)

    synth = check_synth_provenance()

    rows: list[dict] = []
    for split in SPLITS:
        for p in sorted((DATA / split).glob("*.jpg")):
            row = summarize_image(p)
            row.update(score_one(fm, p))
            row["split"] = split
            rows.append(row)

    summaries = {s: split_summary(rows, s) for s in SPLITS}

    # FP accounting
    attacks = [r for r in rows if r["split"].startswith("attack_")]
    raw_fps = [
        r
        for r in attacks
        if r["pad_proba"] is not None and r["pad_proba"] >= thr
    ]
    decision_fps = [
        r
        for r in attacks
        if r["pad_proba"] is not None
        and r["pad_proba"] >= thr
        and not r["pad_reject"]
        and not r["inject_fallback"]
    ]

    # Feature comparison groups
    fp_haar = [
        r
        for r in rows
        if r["split"] == "attack_side"
        and not r["inject_fallback"]
        and r["pad_proba"] is not None
        and r["pad_proba"] >= thr
    ]
    # "true negative" attack_side = correctly rejected. With only 8 sides all
    # scoring high, TN may be empty / only fallbacks fail-closed.
    tn_side = [
        r
        for r in rows
        if r["split"] == "attack_side"
        and (
            (r["pad_proba"] is not None and r["pad_proba"] < thr)
            or r["pad_reject"]
        )
    ]
    # Other attack TNs (blur/screen correctly below thr)
    tn_other = [
        r
        for r in attacks
        if r["split"] != "attack_side"
        and r["pad_proba"] is not None
        and r["pad_proba"] < thr
    ]
    rng = np.random.default_rng(0)
    tn_other_sample = list(rng.choice(tn_other, size=min(6, len(tn_other)), replace=False)) if tn_other else []
    genuine_ok = [
        r
        for r in rows
        if r["split"] == "genuine" and not r["inject_fallback"]
    ]
    genuine_sample = list(
        rng.choice(genuine_ok, size=min(6, len(genuine_ok)), replace=False)
    ) if genuine_ok else []

    def feat_mean(group: list[dict]) -> dict | None:
        if not group:
            return None
        keys = list(FACE_PAD_FEATURE_KEYS)
        mat = np.array([r["feat_vec"] for r in group], dtype=np.float64)
        return {
            k: {"mean": float(mat[:, i].mean()), "std": float(mat[:, i].std())}
            for i, k in enumerate(keys)
        }

    report = {
        "driver_id": DRIVER,
        "store": str(STORE),
        "threshold": thr,
        "stage2_info": fm.stage2_info,
        "feature_keys": list(FACE_PAD_FEATURE_KEYS),
        "synth_provenance": synth,
        "split_summaries": {
            k: {
                **v,
                "resolutions": [list(t) for t in v.get("resolutions", [])],
            }
            for k, v in summaries.items()
        },
        "fp_accounting": {
            "raw_pad_ge_thr": {
                "n": len(raw_fps),
                "files": [
                    {
                        "file": r["file"],
                        "split": r["split"],
                        "pad_proba": r["pad_proba"],
                        "inject_fallback": r["inject_fallback"],
                        "pad_reject": r["pad_reject"],
                        "face_frac": r["face_frac"],
                        "frontal_ok": r["frontal_ok"],
                    }
                    for r in raw_fps
                ],
            },
            "decision_fps_haar_ok_pad_pass": {
                "n": len(decision_fps),
                "files": [
                    {
                        "file": r["file"],
                        "pad_proba": r["pad_proba"],
                        "face_frac": r["face_frac"],
                        "frontal_ok": r["frontal_ok"],
                    }
                    for r in decision_fps
                ],
            },
            "note": (
                "raw_pad_ge_thr counts diagnostic proba>=thr including fail-closed "
                "fallbacks; decision_fps are Haar-OK samples that actually PAD-pass."
            ),
        },
        "feature_groups": {
            "fp_haar_ok_attack_side": {
                "n": len(fp_haar),
                "files": [
                    {
                        "file": r["file"],
                        "pad_proba": r["pad_proba"],
                        "face_frac": r["face_frac"],
                        "frontal_ok": r["frontal_ok"],
                        "feats": r["feats"],
                        "brightness": r["brightness"],
                        "sharpness": r["sharpness"],
                    }
                    for r in fp_haar
                ],
                "feat_mean": feat_mean(fp_haar),
            },
            "tn_attack_side": {
                "n": len(tn_side),
                "files": [
                    {
                        "file": r["file"],
                        "pad_proba": r["pad_proba"],
                        "pad_reject": r["pad_reject"],
                        "inject_fallback": r["inject_fallback"],
                        "face_frac": r["face_frac"],
                        "feats": r["feats"],
                    }
                    for r in tn_side
                ],
                "feat_mean": feat_mean(tn_side),
            },
            "tn_other_attack_sample": {
                "n": len(tn_other_sample),
                "files": [
                    {
                        "file": r["file"],
                        "pad_proba": r["pad_proba"],
                        "feats": r["feats"],
                    }
                    for r in tn_other_sample
                ],
                "feat_mean": feat_mean(tn_other_sample),
            },
            "genuine_sample": {
                "n": len(genuine_sample),
                "files": [
                    {
                        "file": r["file"],
                        "pad_proba": r["pad_proba"],
                        "face_frac": r["face_frac"],
                        "feats": r["feats"],
                    }
                    for r in genuine_sample
                ],
                "feat_mean": feat_mean(genuine_sample),
            },
            "genuine_all_feat_mean": feat_mean(genuine_ok),
        },
        "attack_side_per_file": [
            r for r in rows if r["split"] == "attack_side"
        ],
        "variety": {
            "attack_side_n": summaries["attack_side"]["n"],
            "attack_blur_n": summaries["attack_blur"]["n"],
            "attack_replay_screen_n": summaries["attack_replay_screen"]["n"],
            "genuine_n": summaries["genuine"]["n"],
            "enroll_n": summaries["enroll"]["n"],
            "attack_side_haar_ok": summaries["attack_side"]["haar_ok"],
            "attack_side_fallback": summaries["attack_side"]["fallback"],
            "attack_side_mtime_span": (
                summaries["attack_side"]["mtime_min"],
                summaries["attack_side"]["mtime_max"],
            ),
            "genuine_mtime_span": (
                summaries["genuine"]["mtime_min"],
                summaries["genuine"]["mtime_max"],
            ),
            "synth_yaw_signs_if_synth": [
                r.get("yaw_sign") for r in synth["side"]
            ],
            "distinct_enroll_sources_if_synth": sorted(
                {r.get("enroll_src") for r in synth["side"]}
            ),
        },
    }

    OUT.write_text(json.dumps(_jsonable(report), indent=2))
    print(
        json.dumps(
            _jsonable(
                {
                    "wrote": str(OUT),
                    "threshold": thr,
                    "synth_side_looks_synth": synth["side_looks_synth"],
                    "synth_side_mean_mse": synth["side_mean_mse"],
                    "synth_blur_looks_synth": synth["blur_looks_synth"],
                    "synth_blur_mean_mse": synth["blur_mean_mse"],
                    "split_summaries": report["split_summaries"],
                    "fp_accounting": report["fp_accounting"],
                    "variety": report["variety"],
                    "feat_means": {
                        "fp_haar_ok_attack_side": report["feature_groups"][
                            "fp_haar_ok_attack_side"
                        ]["feat_mean"],
                        "tn_attack_side": report["feature_groups"]["tn_attack_side"][
                            "feat_mean"
                        ],
                        "tn_other_attack_sample": report["feature_groups"][
                            "tn_other_attack_sample"
                        ]["feat_mean"],
                        "genuine_all": report["feature_groups"][
                            "genuine_all_feat_mean"
                        ],
                    },
                    "attack_side_files": [
                        {
                            "file": r["file"],
                            "pad_proba": r["pad_proba"],
                            "pad_reject": r["pad_reject"],
                            "inject_fallback": r["inject_fallback"],
                            "face_frac": r["face_frac"],
                            "frontal_ok": r["frontal_ok"],
                            "brightness": r["brightness"],
                            "sharpness": r["sharpness"],
                            "wh": r["wh"],
                            "mtime": r["mtime"],
                            "feats": r["feats"],
                        }
                        for r in rows
                        if r["split"] == "attack_side"
                    ],
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
