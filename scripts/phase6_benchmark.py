#!/usr/bin/env python3
"""Phase 6 / Sprint 6 — full paper-prep benchmark.

Collects FAR/FRR/EER/ROC, PAD (APCER/BPCER), risk (P/R/F1/AUC), latency,
system baselines (OTP / static MFA / single-modality / staged), and ablations
into ``phases/phase6_sprint6.json`` + ``phases/phase6.md``.

Usage:
  # Live bio scoring (voice+face matchers) + risk ONNX val metrics:
  python scripts/phase6_benchmark.py

  # Rebuild tables from cached JSON / profiles only (no ECAPA/face IO):
  python scripts/phase6_benchmark.py --offline
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
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

# Synth finger stand-in until FingerNet+HW (documented in report).
FINGER_GENUINE_PROXY = 0.90
FINGER_ATTACK_PROXY = 0.20


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def _roc_curve(genuine: list[float], attack: list[float], n: int = 201) -> list[dict]:
    """Threshold sweep → FAR/FRR + TPR/FPR for ROC plotting."""
    if not genuine:
        return []
    pts: list[dict] = []
    for thr in np.linspace(0.0, 1.0, n):
        far, frr = far_frr(genuine, attack, float(thr))
        pts.append(
            {
                "thr": round(float(thr), 4),
                "far": round(far, 4),
                "frr": round(frr, 4),
                "tpr": round(1.0 - frr, 4),
                "fpr": round(far, 4),
            }
        )
    return pts


def _auc_trapezoid(roc: list[dict]) -> float | None:
    """ROC-AUC from (fpr, tpr) points (sorted by fpr)."""
    if not roc:
        return None
    pts = sorted({(p["fpr"], p["tpr"]) for p in roc})
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    trap = getattr(np, "trapezoid", None) or np.trapz
    return round(float(trap(ys, xs)), 4)


def _modality_block(
    genuine: list[float], attack: list[float], by_class: dict[str, list[float]]
) -> dict:
    metrics = eer_metrics(genuine, attack)
    roc = _roc_curve(genuine, attack)
    out = {
        "genuine": summarize(genuine),
        "attack": summarize(attack),
        "metrics": metrics,
        "roc_auc": _auc_trapezoid(roc),
        "roc": roc,
        "by_class": {},
    }
    for name, scores in by_class.items():
        m = eer_metrics(genuine, scores) if genuine and scores else {}
        out["by_class"][name] = {
            "scores": summarize(scores),
            "metrics": m,
        }
    return out


def score_biometrics(store: Path, data: Path, driver_id: str, *, raw: bool) -> dict:
    import os

    import cv2

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher

    if raw:
        os.environ["DRIVEAUTH_STAGE2_RAW"] = "1"
    else:
        os.environ.pop("DRIVEAUTH_STAGE2_RAW", None)

    vm = VoiceMatcher.load(str(store / "enroll"), driver_id, store_dir=str(store))
    fm = FaceMatcher.load(str(store), driver_id)
    if not vm.ready or not fm.ready:
        raise SystemExit("VoiceMatcher / FaceMatcher not ready")

    voice_genuine: list[float] = []
    voice_by: dict[str, list[float]] = {k: [] for k in VOICE_ATTACKS}
    for p in sorted((data / "voice" / "genuine").glob("*.wav")):
        r = vm.score(load_wav(p))
        if r.score is not None:
            voice_genuine.append(float(r.score))
    for split in VOICE_ATTACKS:
        for p in sorted((data / "voice" / split).glob("*.wav")):
            r = vm.score(load_wav(p))
            voice_by[split].append(float(r.score) if r.score is not None else 0.0)
    voice_attack = [s for xs in voice_by.values() for s in xs]

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

    voice = _modality_block(voice_genuine, voice_attack, voice_by)
    face = _modality_block(face_genuine, face_attack, face_by)
    face["pad_attack_reject_rate"] = (
        round(pad_reject_attack / max(n_face_attack, 1), 4) if n_face_attack else None
    )
    face["pad_genuine_reject_rate"] = (
        round(pad_reject_genuine / max(n_face_genuine, 1), 4)
        if n_face_genuine
        else None
    )
    face["n_scored_attack"] = n_face_attack
    face["n_scored_genuine"] = n_face_genuine

    return {
        "raw": bool(raw),
        "voice_scores": {"genuine": voice_genuine, "attack": voice_attack, "by_class": voice_by},
        "face_scores": {"genuine": face_genuine, "attack": face_attack, "by_class": face_by},
        "voice": voice,
        "face": face,
    }


def pad_report(store: Path, face_block: dict) -> dict:
    meta = _load_json(store / "face_pad.json")
    return {
        "source": str(store / "face_pad.json"),
        "threshold": meta.get("threshold"),
        "apcer": meta.get("apcer_at_thr"),
        "bpcer": meta.get("bpcer_at_thr"),
        "loo_auc": meta.get("loo_auc"),
        "val_auc": meta.get("val_auc"),
        "operational_attack_reject_rate": face_block.get("pad_attack_reject_rate"),
        "operational_genuine_reject_rate": face_block.get("pad_genuine_reject_rate"),
        "note": "APCER/BPCER from Stage-2 face_pad trainer; operational rates from matcher path",
    }


def risk_report(store: Path, csv_path: Path, *, offline: bool) -> dict:
    meta = _load_json(store / "risk_gbt.json")
    out: dict = {
        "source": str(store / "risk_gbt.json"),
        "n": meta.get("n"),
        "n_suspicious": meta.get("n_suspicious"),
        "n_legit": meta.get("n_legit"),
        "val_auc": meta.get("val_auc") or meta.get("onnx_auc"),
        "val_acc": meta.get("val_acc@0.5") or meta.get("onnx_acc@0.5"),
        "train_auc": meta.get("train_auc"),
        "brier_score": (meta.get("calibration") or {}).get("brier_score"),
        "val_mean_risk_legit": meta.get("val_mean_risk_legit"),
        "val_mean_risk_suspicious": meta.get("val_mean_risk_suspicious"),
    }
    if offline or not (store / "risk_gbt.onnx").is_file() or not csv_path.is_file():
        # Preserve P/R/F1 from a prior live dump when rebuilding tables offline.
        return out

    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import train_test_split

    from scripts.train_risk_gbt import load_csv

    X, y, _, _ = load_csv(csv_path)
    _, X_va, _, y_va = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    import onnxruntime as ort

    sess = ort.InferenceSession(
        str(store / "risk_gbt.onnx"), providers=["CPUExecutionProvider"]
    )
    name = sess.get_inputs()[0].name
    X_va = X_va.astype(np.float32)
    risks = np.empty(len(X_va), dtype=np.float64)
    # Chunked batch=64 (some ORT exports are picky about huge batches).
    bs = 64
    for i in range(0, len(X_va), bs):
        chunk = X_va[i : i + bs]
        outs = sess.run(None, {name: chunk})
        if len(outs) >= 2:
            prob = np.asarray(outs[1])
            if prob.ndim == 2 and prob.shape[1] >= 2:
                risks[i : i + len(chunk)] = prob[:, 1]
            else:
                risks[i : i + len(chunk)] = np.asarray(outs[1]).ravel()[: len(chunk)]
        else:
            risks[i : i + len(chunk)] = np.asarray(outs[0]).ravel()[: len(chunk)]
    pred = (risks >= 0.5).astype(int)
    out.update(
        {
            "val_auc": round(float(roc_auc_score(y_va, risks)), 4),
            "val_acc": round(float(accuracy_score(y_va, pred)), 4),
            "precision": round(float(precision_score(y_va, pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_va, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y_va, pred, zero_division=0)), 4),
            "prf_note": "stratified val 20% seed=42 @ thr=0.5 (suspicious=positive)",
        }
    )
    return out


def _parse_latency_txt(path: Path) -> dict:
    text = path.read_text() if path.is_file() else ""
    out: dict = {"source": str(path), "exists": path.is_file()}

    def grab(pattern: str) -> dict | None:
        m = re.search(pattern, text)
        if not m:
            return None
        return {
            "p50_ms": float(m.group(1)),
            "p95_ms": float(m.group(2)),
            "max_ms": float(m.group(3)),
        }

    out["voice"] = grab(
        r"ECAPA voice\.score:\s+p50=([\d.]+)ms\s+p95=([\d.]+)ms\s+max=([\d.]+)ms"
    )
    out["face"] = grab(
        r"Face capture_and_score:\s+p50=([\d.]+)ms\s+p95=([\d.]+)ms\s+max=([\d.]+)ms"
    )
    out["micro"] = grab(
        r"Micro \(early-stop voice\):\s+p50=([\d.]+)ms\s+p95=([\d.]+)ms\s+max=([\d.]+)ms"
    )
    out["high"] = grab(
        r"High-value.*:\s+p50=([\d.]+)ms\s+p95=([\d.]+)ms\s+max=([\d.]+)ms"
    )
    # Phase 1 mock profiles use a different shape.
    m = re.search(
        r"p50[=:]?\s*([\d.]+)\s*ms.*?p95[=:]?\s*([\d.]+)\s*ms.*?max[=:]?\s*([\d.]+)\s*ms",
        text,
        re.I | re.S,
    )
    if out["micro"] is None and m:
        out["mock_auth"] = {
            "p50_ms": float(m.group(1)),
            "p95_ms": float(m.group(2)),
            "max_ms": float(m.group(3)),
        }
    status = re.search(r"Status:\s*(\w+)", text)
    out["status"] = status.group(1) if status else None
    return out


def latency_report(phases: Path) -> dict:
    return {
        "phase1_mac": _parse_latency_txt(phases / "mac.txt"),
        "phase1_thor": _parse_latency_txt(phases / "thor.txt"),
        "phase2a_mac": _parse_latency_txt(phases / "phase2a-mac.txt"),
        "phase2a_thor": _parse_latency_txt(phases / "phase2a-thor.txt"),
        "budget_real_auth_p95_ms": 200.0,
        "budget_mock_auth_p95_ms": 10.0,
    }


def intent_report() -> dict:
    from driveauth.intent import is_payment_utterance, parse_transaction_intent

    cases = [
        ("pay raj 200", True, 200.0, "Raj", "pay"),
        ("pay Amit 500", True, 500.0, "Amit", "pay"),
        ("send 1000 to ravi", True, 1000.0, "Ravi", "transfer"),
        ("transfer 2500 to Neha", True, 2500.0, "Neha", "transfer"),
        ("pay Mom ₹1500", True, 1500.0, "Mom", "pay"),
        ("recharge 299", True, 299.0, "", "recharge"),
        ("open navigation", False, 0.0, "", ""),
        ("play music", False, 0.0, "", ""),
        ("increase AC", False, 0.0, "", ""),
        ("call mom", False, 0.0, "", ""),
    ]
    parse_ok = 0
    slot_ok = 0
    payment_ok = 0
    details = []
    for text, is_pay, amount, bene, action in cases:
        i = parse_transaction_intent(text)
        pay_hit = is_payment_utterance(text) == is_pay
        payment_ok += int(pay_hit)
        amount_hit = abs(i.amount - amount) < 1e-6
        bene_hit = (i.beneficiary or "") == bene
        action_hit = (not action) or (i.action == action)
        slots = amount_hit and bene_hit and action_hit
        slot_ok += int(slots)
        full = pay_hit and slots
        parse_ok += int(full)
        details.append(
            {
                "text": text,
                "payment_ok": pay_hit,
                "slots_ok": slots,
                "ok": full,
            }
        )
    n = len(cases)
    return {
        "n": n,
        "parsing_accuracy": round(parse_ok / n, 4),
        "slot_accuracy": round(slot_ok / n, 4),
        "payment_gate_accuracy": round(payment_ok / n, 4),
        "details": details,
    }


def _decision_rates(
    genuine_trials: list[tuple[float | None, float | None, float | None]],
    attack_trials: list[tuple[float | None, float | None, float | None]],
    decide_fn,
) -> dict:
    g_accept = sum(1 for t in genuine_trials if decide_fn(*t)[0])
    a_accept = sum(1 for t in attack_trials if decide_fn(*t)[0])
    n_g, n_a = len(genuine_trials), len(attack_trials)
    frr = 1.0 - (g_accept / n_g) if n_g else float("nan")
    far = (a_accept / n_a) if n_a else float("nan")
    stop_mod: dict[str, int] = {}
    for t in genuine_trials:
        ok, mod = decide_fn(*t)
        if ok and mod:
            stop_mod[mod] = stop_mod.get(mod, 0) + 1
    return {
        "n_genuine": n_g,
        "n_attack": n_a,
        "far": round(far, 4),
        "frr": round(frr, 4),
        "genuine_accept_rate": round(1.0 - frr, 4) if n_g else None,
        "early_stop_voice_rate": round(stop_mod.get("voice", 0) / max(n_g, 1), 4),
        "accept_by_modality": stop_mod,
    }


def policy_comparisons(
    voice_g: list[float],
    voice_a: list[float],
    face_g: list[float],
    face_a: list[float],
    bars: dict[str, float],
) -> dict:
    """Compare OTP / static MFA / single-modality / staged on scored sessions."""
    n = min(len(voice_g), len(face_g))
    genuine = [
        (voice_g[i], face_g[i], FINGER_GENUINE_PROXY) for i in range(n)
    ]
    # Cross-product style attack set: each voice attack vs mean face attack,
    # and each face attack vs mean voice attack (covers single-modality spoofs).
    face_a_mean = float(np.mean(face_a)) if face_a else 0.0
    voice_a_mean = float(np.mean(voice_a)) if voice_a else 0.0
    attack: list[tuple[float | None, float | None, float | None]] = []
    for v in voice_a:
        attack.append((v, face_a_mean, FINGER_ATTACK_PROXY))
    for f in face_a:
        attack.append((voice_a_mean, f, FINGER_ATTACK_PROXY))

    bv, bf, bfi = bars["voice"], bars["face"], bars["finger"]

    def otp_only(v, f, fi):
        # Never bio-accepts — always STEP_UP to cellular OTP / PIN.
        return False, None

    def voice_only(v, f, fi):
        ok = v is not None and v >= bv
        return ok, ("voice" if ok else None)

    def face_only(v, f, fi):
        ok = f is not None and f >= bf
        return ok, ("face" if ok else None)

    def finger_only(v, f, fi):
        ok = fi is not None and fi >= bfi
        return ok, ("finger" if ok else None)

    def static_mfa(v, f, fi):
        # Classic AND gate: voice + face both clear bars (2-factor static).
        ok = (
            v is not None
            and f is not None
            and v >= bv
            and f >= bf
        )
        return ok, ("voice+face" if ok else None)

    def staged(v, f, fi):
        if v is not None and v >= bv:
            return True, "voice"
        if f is not None and f >= bf:
            return True, "face"
        if fi is not None and fi >= bfi:
            return True, "finger"
        return False, None

    def staged_no_finger(v, f, fi):
        if v is not None and v >= bv:
            return True, "voice"
        if f is not None and f >= bf:
            return True, "face"
        return False, None

    systems = {
        "otp_only": {
            "policy": "Always STEP_UP; bio never Accepts. FAR below assumes OTP channel secure.",
            **_decision_rates(genuine, attack, otp_only),
            "far_with_secure_otp": 0.0,
            "ux_friction": 1.0,
        },
        "voice_only": {
            "policy": f"Accept iff voice ≥ {bv}",
            **_decision_rates(genuine, attack, voice_only),
        },
        "face_only": {
            "policy": f"Accept iff face ≥ {bf}",
            **_decision_rates(genuine, attack, face_only),
        },
        "finger_only_proxy": {
            "policy": f"Accept iff finger ≥ {bfi} (synth proxy scores)",
            **_decision_rates(genuine, attack, finger_only),
            "caveat": "HW-gated — FingerNet not enrolled; genuine=0.90 / attack=0.20 stand-in",
        },
        "static_mfa_voice_and_face": {
            "policy": f"Accept iff voice ≥ {bv} AND face ≥ {bf}",
            **_decision_rates(genuine, attack, static_mfa),
        },
        "staged_voice_face": {
            "policy": "Voice→Face ladder; no finger (current shipping without ManualScores finger)",
            **_decision_rates(genuine, attack, staged_no_finger),
        },
        "staged_full_proxy": {
            "policy": "Voice→Face→Finger ladder (finger synth proxy)",
            **_decision_rates(genuine, attack, staged),
            "caveat": "Finger scores are ManualScores-style proxies until HW",
        },
    }
    return {
        "bars": bars,
        "n_genuine_sessions": n,
        "n_attack_sessions": len(attack),
        "systems": systems,
    }


def comparisons_at_far0_eval_bar(
    voice_g: list[float],
    voice_a: list[float],
    face_g: list[float],
    face_a: list[float],
    shipping_bars: dict[str, float],
) -> dict:
    """Same systems at the lowest voice bar with FAR=0 on this eval set.

    Shipping voice bar (0.72) sits above current Stage-2 genuine max (~0.66),
    so every bio system FRR=1 there — the FAR=0 operating point is the useful
    comparison for the paper (still not shipped).
    """
    # Ceil to 2 decimals like calibrate_bio_thresholds.
    far0 = None
    for thr in np.linspace(0.0, 1.0, 1001):
        far, _ = far_frr(voice_g, voice_a, float(thr))
        if far <= 1e-12:
            import math

            far0 = math.ceil(thr * 100 - 1e-12) / 100.0
            break
    if far0 is None:
        far0 = float(shipping_bars["voice"])
    suggested = {
        "voice": float(far0),
        "face": float(shipping_bars["face"]),
        "finger": float(shipping_bars["finger"]),
    }
    block = policy_comparisons(voice_g, voice_a, face_g, face_a, suggested)
    block["note"] = (
        f"Eval-set FAR≈0 voice bar ({far0:.2f}) on Stage-2 scores; face left "
        "at shipping bar. Not applied as default policy."
    )
    return block


def ablations(
    voice_g: list[float],
    voice_a: list[float],
    face_g: list[float],
    face_a: list[float],
    bars: dict[str, float],
    staged2: dict | None,
    raw: dict | None,
) -> dict:
    """Early-stop vs security floor + Stage-2 heads + ladder-bar sweep."""
    n = min(len(voice_g), len(face_g))
    genuine = [(voice_g[i], face_g[i], None) for i in range(n)]
    face_a_mean = float(np.mean(face_a)) if face_a else 0.0
    voice_a_mean = float(np.mean(voice_a)) if voice_a else 0.0
    attack = [(v, face_a_mean, None) for v in voice_a] + [
        (voice_a_mean, f, None) for f in face_a
    ]

    sweep = []
    for voice_bar in np.linspace(0.50, 0.85, 15):
        vb = float(voice_bar)

        def decide(v, f, fi, _vb=vb):
            if v is not None and v >= _vb:
                return True, "voice"
            if f is not None and f >= bars["face"]:
                return True, "face"
            return False, None

        rates = _decision_rates(genuine, attack, decide)
        sweep.append(
            {
                "voice_bar": round(vb, 3),
                "far": rates["far"],
                "frr": rates["frr"],
                "early_stop_voice_rate": rates["early_stop_voice_rate"],
            }
        )

    # Security floor: force full voice+face probe (no early-stop).
    def force_full(v, f, fi):
        ok = (
            v is not None
            and f is not None
            and v >= bars["voice"]
            and f >= bars["face"]
        )
        return ok, ("voice+face" if ok else None)

    def early_stop(v, f, fi):
        if v is not None and v >= bars["voice"]:
            return True, "voice"
        if f is not None and f >= bars["face"]:
            return True, "face"
        return False, None

    early = _decision_rates(genuine, attack, early_stop)
    full = _decision_rates(genuine, attack, force_full)

    # Operating point from sweep with lowest |FAR−FRR| among voice bars ≤ 0.65
    # (shipping 0.72 is FAR=0 / FRR=1 — ablation is vacuous there).
    useful = [r for r in sweep if r["voice_bar"] <= 0.65]
    best = min(useful, key=lambda r: abs(r["far"] - r["frr"])) if useful else None
    op_early = op_full = None
    if best is not None:
        vb = float(best["voice_bar"])

        def early_op(v, f, fi, _vb=vb):
            if v is not None and v >= _vb:
                return True, "voice"
            if f is not None and f >= bars["face"]:
                return True, "face"
            return False, None

        def full_op(v, f, fi, _vb=vb):
            ok = (
                v is not None
                and f is not None
                and v >= _vb
                and f >= bars["face"]
            )
            return ok, ("voice+face" if ok else None)

        op_early = _decision_rates(genuine, attack, early_op)
        op_full = _decision_rates(genuine, attack, full_op)
        op_early["voice_bar"] = vb
        op_full["voice_bar"] = vb

    stage2_vs_raw = None
    if staged2 and raw:
        stage2_vs_raw = {
            "voice_eer_stage2": (staged2.get("voice") or {}).get("metrics", {}).get("eer"),
            "voice_eer_raw": (raw.get("voice") or {}).get("metrics", {}).get("eer"),
            "face_eer_stage2": (staged2.get("face") or {}).get("metrics", {}).get("eer"),
            "face_eer_raw": (raw.get("face") or {}).get("metrics", {}).get("eer"),
            "face_pad_attack_reject_stage2": (staged2.get("face") or {}).get(
                "pad_attack_reject_rate"
            ),
            "face_attack_mean_stage2": ((staged2.get("face") or {}).get("attack") or {}).get(
                "mean"
            ),
            "face_attack_mean_raw": ((raw.get("face") or {}).get("attack") or {}).get("mean"),
            "note": "Stage-2 PAD+calibrators vs DRIVEAUTH_STAGE2_RAW cosine-only",
        }

    out_abl = {
        "early_stop_vs_security_floor": {
            "at_shipping_bars": {
                "early_stop_staged": early,
                "force_full_mfa": full,
                "delta_far": round(early["far"] - full["far"], 4),
                "delta_frr": round(early["frr"] - full["frr"], 4),
            },
            "at_balanced_voice_bar": {
                "early_stop_staged": op_early,
                "force_full_mfa": op_full,
                "delta_far": (
                    round(op_early["far"] - op_full["far"], 4)
                    if op_early and op_full
                    else None
                ),
                "delta_frr": (
                    round(op_early["frr"] - op_full["frr"], 4)
                    if op_early and op_full
                    else None
                ),
            },
            "note": (
                "Early-stop improves UX (lower FRR) when voice clears the bar; "
                "security floor = static AND requires both modalities. "
                "Shipping bars yield FAR=0/FRR=1 for both — use balanced-bar row."
            ),
        },
        "ladder_voice_bar_sweep": sweep,
        "stage2_vs_raw_2a": stage2_vs_raw,
    }
    return out_abl


def behavioral_report(store: Path) -> dict:
    meta = _load_json(store / "behavioral_bakeoff.json")
    if not meta:
        return {"available": False}
    w = meta.get("winner") or {}
    return {
        "available": True,
        "winner": w.get("name"),
        "auc": w.get("auc"),
        "accuracy": w.get("accuracy"),
        "genuine_mean": w.get("genuine_mean"),
        "attack_mean": w.get("attack_mean"),
        "n_windows": meta.get("n_windows"),
        "caveat": meta.get("note")
        or "Synth CAN stand-in — not production biometric quality",
    }


def ood_report(phases: Path) -> dict:
    meta = _load_json(phases / "phase2a_ood_eval.json")
    if not meta:
        return {"available": False}
    return {
        "available": True,
        "voice_reject_rate": (meta.get("voice") or {}).get("reject_rate"),
        "face_reject_rate": (meta.get("face") or {}).get("reject_rate"),
        "source": str(phases / "phase2a_ood_eval.json"),
    }


def scores_from_cached_bio(bio: dict) -> tuple[list, list, list, list]:
    """Best-effort: offline mode has no per-sample lists — reconstruct from
    summarize is impossible; require prior live dump or empty."""
    vs = bio.get("voice_scores") or {}
    fs = bio.get("face_scores") or {}
    return (
        list(vs.get("genuine") or []),
        list(vs.get("attack") or []),
        list(fs.get("genuine") or []),
        list(fs.get("attack") or []),
    )


def render_markdown(report: dict) -> str:
    bio = report["biometrics"]
    pad = report["pad"]
    risk = report["risk"]
    lat = report["latency"]
    cmp_ = report["comparisons"]["systems"]
    cmp_cal = (report.get("comparisons_at_calibration_bars") or {}).get("systems") or {}
    cal_bars = (report.get("comparisons_at_calibration_bars") or {}).get("bars") or {}
    abl = report["ablations"]
    intent = report["intent"]
    beh = report["behavioral"]
    ood = report["ood"]

    def _m(mod: str) -> dict:
        return (bio.get(mod) or {}).get("metrics") or {}

    v, f = _m("voice"), _m("face")
    mac = lat.get("phase2a_mac") or {}
    thor = lat.get("phase2a_thor") or {}

    lines = [
        "# Phase 6 — Benchmarking (Sprint 6)",
        "",
        f"**Status:** ✅ Done ({report.get('date', '')})",
        "**Exit:** Sprint 6 table populated + ablations filled.",
        "",
        "Artifacts: [`phase6_sprint6.json`](phase6_sprint6.json) · "
        "`python scripts/phase6_benchmark.py`",
        "",
        "## Sprint 6 summary table",
        "",
        "| Category | Metric | Value | Source / notes |",
        "|---|---|---|---|",
        f"| Biometrics · voice | EER | {v.get('eer')} | thr={v.get('eer_thr')} "
        f"FAR={v.get('eer_far')} FRR={v.get('eer_frr')} |",
        f"| Biometrics · voice | ROC-AUC | {(bio.get('voice') or {}).get('roc_auc')} | "
        f"threshold sweep on Stage-2 scores |",
        f"| Biometrics · face | EER | {f.get('eer')} | thr={f.get('eer_thr')} "
        f"FAR={f.get('eer_far')} FRR={f.get('eer_frr')} |",
        f"| Biometrics · face | ROC-AUC | {(bio.get('face') or {}).get('roc_auc')} | "
        f"PAD-gated scores (reject→0) |",
        f"| PAD | APCER / BPCER | {pad.get('apcer')} / {pad.get('bpcer')} | "
        f"`face_pad.json` thr={pad.get('threshold')} |",
        f"| PAD | Attack reject (ops) | {pad.get('operational_attack_reject_rate')} | "
        f"matcher path on attack set |",
        f"| Risk | Val ROC-AUC | {risk.get('val_auc')} | LightGBM→ONNX · 50k txns |",
        f"| Risk | Acc / P / R / F1 | {risk.get('val_acc')} / {risk.get('precision')} / "
        f"{risk.get('recall')} / {risk.get('f1')} | @0.5 on stratified val |",
        f"| Risk | Brier | {risk.get('brier_score')} | calibration sidecar |",
        f"| Intent | Parse / slot acc | {intent.get('parsing_accuracy')} / "
        f"{intent.get('slot_accuracy')} | fixed 10-utt harness |",
        f"| Latency · Mac 2a | micro p95 | {(mac.get('micro') or {}).get('p95_ms')} ms | "
        f"`phase2a-mac.txt` |",
        f"| Latency · Thor 2a | micro / high p95 | "
        f"{(thor.get('micro') or {}).get('p95_ms')} / "
        f"{(thor.get('high') or {}).get('p95_ms')} ms | `phase2a-thor.txt` · CUDA |",
        f"| Behavioral (synth) | Winner AUC | {beh.get('auc')} | "
        f"{beh.get('winner')} — {beh.get('caveat', '')[:60]} |",
        f"| OOD Stage 1 | Voice / face reject | {ood.get('voice_reject_rate')} / "
        f"{ood.get('face_reject_rate')} | `phase2a_ood_eval.json` |",
        "",
        "## System comparison (vs OTP / static MFA / single-modality / staged)",
        "",
        f"Bars: voice≥{cmp_.get('otp_only') and report['comparisons']['bars']['voice']} · "
        f"face≥{report['comparisons']['bars']['face']} · "
        f"finger≥{report['comparisons']['bars']['finger']} (proxy).",
        "",
        "| System | FAR | FRR | Genuine accept | Notes |",
        "|---|---|---|---|---|",
    ]
    order = [
        "otp_only",
        "voice_only",
        "face_only",
        "finger_only_proxy",
        "static_mfa_voice_and_face",
        "staged_voice_face",
        "staged_full_proxy",
    ]
    for key in order:
        s = cmp_[key]
        far = s.get("far_with_secure_otp", s.get("far"))
        lines.append(
            f"| `{key}` | {far} | {s.get('frr')} | {s.get('genuine_accept_rate')} | "
            f"{s.get('caveat') or s.get('policy', '')} |"
        )

    if cmp_cal:
        lines += [
            "",
            "### At eval-set FAR≈0 voice bar "
            f"(voice≥{cal_bars.get('voice')} · face≥{cal_bars.get('face')} · **not shipped**)",
            "",
            "| System | FAR | FRR | Genuine accept |",
            "|---|---|---|---|",
        ]
        for key in (
            "voice_only",
            "static_mfa_voice_and_face",
            "staged_voice_face",
            "staged_full_proxy",
        ):
            s = cmp_cal[key]
            far = s.get("far_with_secure_otp", s.get("far"))
            lines.append(
                f"| `{key}` | {far} | {s.get('frr')} | {s.get('genuine_accept_rate')} |"
            )

    es = abl["early_stop_vs_security_floor"]
    ship = es.get("at_shipping_bars") or es
    bal = es.get("at_balanced_voice_bar") or {}
    bal_e = bal.get("early_stop_staged") or {}
    bal_f = bal.get("force_full_mfa") or {}
    lines += [
        "",
        "## Ablations",
        "",
        "### A1 — Early-stop vs security floor",
        "",
        "| Setting | Variant | FAR | FRR | Early-stop voice rate |",
        "|---|---|---|---|---|",
        f"| Shipping bars | Staged early-stop | "
        f"{(ship.get('early_stop_staged') or {}).get('far')} | "
        f"{(ship.get('early_stop_staged') or {}).get('frr')} | "
        f"{(ship.get('early_stop_staged') or {}).get('early_stop_voice_rate')} |",
        f"| Shipping bars | Force full MFA (AND) | "
        f"{(ship.get('force_full_mfa') or {}).get('far')} | "
        f"{(ship.get('force_full_mfa') or {}).get('frr')} | 0 |",
        f"| Balanced voice bar "
        f"({bal_e.get('voice_bar', '—')}) | Staged early-stop | "
        f"{bal_e.get('far')} | {bal_e.get('frr')} | "
        f"{bal_e.get('early_stop_voice_rate')} |",
        f"| Balanced voice bar | Force full MFA (AND) | "
        f"{bal_f.get('far')} | {bal_f.get('frr')} | 0 |",
        f"| Balanced | Δ (early − full) | {bal.get('delta_far')} | "
        f"{bal.get('delta_frr')} | — |",
        "",
        f"_{es['note']}_",
        "",
        "### A2 — Ladder voice-bar sweep (face bar fixed)",
        "",
        "| Voice bar | FAR | FRR | Early-stop voice rate |",
        "|---|---|---|---|",
    ]
    for row in abl["ladder_voice_bar_sweep"]:
        lines.append(
            f"| {row['voice_bar']:.3f} | {row['far']} | {row['frr']} | "
            f"{row['early_stop_voice_rate']} |"
        )

    s2 = abl.get("stage2_vs_raw_2a") or {}
    lines += [
        "",
        "### A3 — Stage-2 heads (PAD+calibrators) vs raw 2a",
        "",
        "| | Voice EER | Face EER | Face attack mean | PAD attack reject |",
        "|---|---|---|---|---|",
        f"| Stage 2 | {s2.get('voice_eer_stage2')} | {s2.get('face_eer_stage2')} | "
        f"{s2.get('face_attack_mean_stage2')} | {s2.get('face_pad_attack_reject_stage2')} |",
        f"| Raw 2a | {s2.get('voice_eer_raw')} | {s2.get('face_eer_raw')} | "
        f"{s2.get('face_attack_mean_raw')} | 0 (no PAD) |",
        "",
        "## Caveats (paper-facing)",
        "",
        "- Face genuine scores sit near ~0.50 after calibration — ladder face bar "
        "0.70 yields high FRR without finger; do **not** ship `phase2b_suggested.env` yet.",
        "- Finger metrics use ManualScores proxies until FingerNet + sensor HW.",
        "- Behavioral bake-off AUC is on **synth CAN** — re-bake on recorder dumps "
        "before citing as production FAR/FRR.",
        "- Risk head trained on synthetic 50k txns; retrain at ~5k real labels.",
        "- OTP-only FAR=0 assumes a secure cellular OTP channel (not measured here).",
        "",
        "## Re-run",
        "",
        "```bash",
        "python scripts/phase6_benchmark.py",
        "python scripts/phase6_benchmark.py --offline   # tables from cached JSON only",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    ap.add_argument("--data", default=str(ROOT / "data" / "driver1"))
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--phases", default=str(ROOT / "phases"))
    ap.add_argument(
        "--offline",
        action="store_true",
        help="Skip live bio/risk scoring; reuse phase6_sprint6.json score lists "
        "or phase2b_bio_eval aggregates (comparisons need prior --live scores).",
    )
    ap.add_argument("--skip-raw", action="store_true", help="Skip raw-2a ablation pass")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    args = ap.parse_args()

    store = Path(args.store)
    data = Path(args.data)
    phases = Path(args.phases)
    out_json = Path(args.out_json) if args.out_json else phases / "phase6_sprint6.json"
    out_md = Path(args.out_md) if args.out_md else phases / "phase6.md"

    from driveauth import config

    bars = {
        "voice": float(config.LADDER_ACCEPT_VOICE),
        "face": float(config.LADDER_ACCEPT_FACE),
        "finger": float(config.LADDER_ACCEPT_FINGER),
    }

    prev = _load_json(out_json)

    if args.offline:
        bio = prev.get("biometrics") or _load_json(phases / "phase2b_bio_eval.json")
        # Ensure ROC exists even in offline rebuild from phase2b (no roc field).
        for mod in ("voice", "face"):
            block = bio.get(mod) or {}
            if "roc" not in block and prev.get("biometrics"):
                block = (prev.get("biometrics") or {}).get(mod) or block
            bio[mod] = block
        voice_g, voice_a, face_g, face_a = scores_from_cached_bio(bio)
        if not voice_g:
            # Fall back to previous live dump only.
            voice_g, voice_a, face_g, face_a = scores_from_cached_bio(prev.get("biometrics") or {})
        raw_bio = prev.get("biometrics_raw_2a")
        print("Offline: using cached score lists / prior phase6 dump")
    else:
        print("Scoring Stage-2 biometrics…")
        live = score_biometrics(store, data, args.driver_id, raw=False)
        bio = {
            "tag": "phase6_stage2",
            "store": str(store),
            "raw": False,
            "voice": live["voice"],
            "face": live["face"],
            "voice_scores": live["voice_scores"],
            "face_scores": live["face_scores"],
        }
        voice_g = live["voice_scores"]["genuine"]
        voice_a = live["voice_scores"]["attack"]
        face_g = live["face_scores"]["genuine"]
        face_a = live["face_scores"]["attack"]
        raw_bio = None
        if not args.skip_raw:
            print("Scoring raw 2a biometrics (ablation)…")
            raw_live = score_biometrics(store, data, args.driver_id, raw=True)
            raw_bio = {
                "tag": "phase6_raw_2a",
                "raw": True,
                "voice": raw_live["voice"],
                "face": raw_live["face"],
            }

    if not voice_g or not face_g:
        raise SystemExit(
            "No per-sample scores available. Run without --offline first "
            "(needs enrolled VoiceMatcher/FaceMatcher)."
        )

    pad = pad_report(store, bio.get("face") or {})
    risk = risk_report(
        store, ROOT / "data" / "driver1" / "transaction" / "txns.csv", offline=args.offline
    )
    if args.offline and prev.get("risk"):
        for k in ("precision", "recall", "f1", "prf_note", "val_acc", "val_auc"):
            if risk.get(k) is None and prev["risk"].get(k) is not None:
                risk[k] = prev["risk"][k]
    if args.offline and prev.get("biometrics_raw_2a") and raw_bio is None:
        raw_bio = prev.get("biometrics_raw_2a")
    lat = latency_report(phases)
    intent = intent_report()
    comparisons = policy_comparisons(voice_g, voice_a, face_g, face_a, bars)
    comparisons_suggested = comparisons_at_far0_eval_bar(
        voice_g, voice_a, face_g, face_a, bars
    )
    abl = ablations(voice_g, voice_a, face_g, face_a, bars, bio, raw_bio)
    beh = behavioral_report(store)
    ood = ood_report(phases)

    report = {
        "phase": 6,
        "sprint": 6,
        "date": date.today().isoformat(),
        "store": str(store),
        "data": str(data),
        "offline": bool(args.offline),
        "biometrics": bio,
        "biometrics_raw_2a": raw_bio,
        "pad": pad,
        "risk": risk,
        "latency": lat,
        "intent": intent,
        "behavioral": beh,
        "ood": ood,
        "comparisons": comparisons,
        "comparisons_at_calibration_bars": comparisons_suggested,
        "ablations": abl,
        "exit": "Sprint 6 table populated + ablations filled",
    }

    # Drop bulky ROC from stdout friendliness — keep in JSON (trim to 41 pts).
    for mod in ("voice", "face"):
        block = report["biometrics"].get(mod) or {}
        roc = block.get("roc") or []
        if len(roc) > 41:
            block["roc"] = roc[::5]
            block["roc_n_full"] = len(roc)
        if raw_bio and mod in (raw_bio or {}):
            rblock = raw_bio[mod]
            rroc = rblock.get("roc") or []
            if len(rroc) > 41:
                rblock["roc"] = rroc[::5]
                rblock["roc_n_full"] = len(rroc)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    out_md.write_text(render_markdown(report))
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    print(
        f"voice EER={v_get(bio)}  face EER={f_get(bio)}  "
        f"risk AUC={risk.get('val_auc')}  "
        f"staged FAR/FRR="
        f"{comparisons['systems']['staged_voice_face']['far']}/"
        f"{comparisons['systems']['staged_voice_face']['frr']}"
    )


def v_get(bio: dict) -> object:
    return ((bio.get("voice") or {}).get("metrics") or {}).get("eer")


def f_get(bio: dict) -> object:
    return ((bio.get("face") or {}).get("metrics") or {}).get("eer")


if __name__ == "__main__":
    main()
