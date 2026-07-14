#!/usr/bin/env python3
"""Phase 2b — calibrate voice/face thresholds from genuine vs attack scores.

Writes phases/phase2b_calibration.json and prints suggested policy.yaml overrides.

Usage:
  python scripts/calibrate_bio_thresholds.py --store ./driveauth_store_phase2a
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
        "p10": round(float(np.percentile(a, 10)), 4),
        "p50": round(float(np.percentile(a, 50)), 4),
        "p90": round(float(np.percentile(a, 90)), 4),
        "min": round(float(a.min()), 4),
        "max": round(float(a.max()), 4),
    }


def _far_frr(genuine: list[float], attack: list[float], thr: float) -> tuple[float, float]:
    g = np.asarray(genuine, dtype=np.float64)
    a = np.asarray(attack, dtype=np.float64)
    frr = float(np.mean(g < thr)) if g.size else float("nan")
    far = float(np.mean(a >= thr)) if a.size else float("nan")
    return far, frr


def _eer_and_ladder_bar(genuine: list[float], attack: list[float]) -> dict:
    """EER + ladder early-accept bar (lowest thr with FAR≈0; escalate absorbs FRR)."""
    if not genuine:
        return {}
    g = np.asarray(genuine, dtype=np.float64)
    a = np.asarray(attack, dtype=np.float64) if attack else np.asarray([0.0])
    best_gap, eer_thr, eer_far, eer_frr = 1.0, 0.5, 1.0, 1.0
    far0_thr: float | None = None
    for thr in np.linspace(0.0, 1.0, 1001):
        far, frr = _far_frr(g.tolist(), a.tolist(), float(thr))
        gap = abs(far - frr)
        if gap < best_gap:
            best_gap, eer_thr, eer_far, eer_frr = gap, float(thr), far, frr
        if far0_thr is None and far <= 1e-12:
            far0_thr = float(thr)
    # Ladder early-accept prefers FAR=0; fall back to EER if overlap is total.
    # Ceil to 2 decimals so banker's round cannot drop below the FAR=0 thr
    # (e.g. 0.715 → 0.72, not 0.71).
    def _ceil2(x: float) -> float:
        return float(np.ceil(np.round(x, 6) * 100.0) / 100.0)

    if far0_thr is not None:
        ladder = _ceil2(far0_thr)
        far, frr = _far_frr(g.tolist(), a.tolist(), ladder)
        ladder_note = "lowest thr with FAR=0 on this set, ceiled to 2-dp (misses escalate)"
    else:
        ladder = _ceil2(eer_thr)
        far, frr = _far_frr(g.tolist(), a.tolist(), ladder)
        ladder_note = "no FAR=0 thr; using EER ceiled to 2-dp (review — high overlap)"
    return {
        "eer_thr": round(eer_thr, 3),
        "eer": round((eer_far + eer_frr) / 2.0, 3),
        "ladder_accept": ladder,
        "ladder_far": round(far, 3),
        "ladder_frr": round(frr, 3),
        "note": ladder_note,
    }


def _suggest(genuine: list[float], attack: list[float]) -> dict:
    """Suggest accept / reject style bars from score distributions."""
    if not genuine:
        return {}
    g = np.asarray(genuine, dtype=np.float64)
    a = np.asarray(attack, dtype=np.float64) if attack else np.array([0.0])
    # Micro accept near genuine p10 (slightly below median of good scores)
    accept_micro = float(np.clip(np.percentile(g, 15), 0.55, 0.95))
    accept_std = float(np.clip(np.percentile(g, 35), accept_micro + 0.03, 0.97))
    accept_high = float(np.clip(np.percentile(g, 55), accept_std + 0.03, 0.99))
    # Reject near attack p90 (or midway if overlap)
    reject = float(np.clip(np.percentile(a, 90) if a.size else 0.45, 0.35, accept_micro - 0.05))
    if reject >= accept_micro:
        reject = max(0.35, accept_micro - 0.08)
    out = {
        "accept_micro": round(accept_micro, 3),
        "accept_standard": round(accept_std, 3),
        "accept_high": round(accept_high, 3),
        "reject": round(reject, 3),
        "note": "Derived from genuine p15/p35/p55 and attack p90; review before shipping.",
    }
    out["ladder"] = _eer_and_ladder_bar(genuine, attack)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate bio thresholds")
    parser.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    parser.add_argument("--data", default=str(ROOT / "data" / "driver1"))
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write suggested trust thresholds into a sidecar env file (does not edit policy.yaml)",
    )
    args = parser.parse_args()

    store = Path(args.store)
    data = Path(args.data)

    from driveauth.matchers.face import FaceMatcher
    from driveauth.matchers.voice import VoiceMatcher

    vm = VoiceMatcher.load(str(store / "enroll"), args.driver_id, store_dir=str(store))
    fm = FaceMatcher.load(str(store), args.driver_id)
    if not vm.ready:
        raise SystemExit("VoiceMatcher not ready — run phase2a_enroll.py first")
    if not fm.ready:
        raise SystemExit("FaceMatcher not ready — run phase2a_enroll.py first")

    voice_genuine, voice_attack = [], []
    for p in sorted((data / "voice" / "genuine").glob("*.wav")):
        r = vm.score(_load_wav(p))
        if r.score is not None:
            voice_genuine.append(float(r.score))
    for split in ("attack_replay", "attack_silent", "attack_other_speaker"):
        for p in sorted((data / "voice" / split).glob("*.wav")):
            r = vm.score(_load_wav(p))
            if r.score is not None:
                voice_attack.append(float(r.score))

    import cv2

    face_genuine, face_attack = [], []
    for p in sorted((data / "face" / "genuine").glob("*.jpg")):
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fm.inject_bgr(bgr)
        r = fm.capture_and_score()
        if r.score is not None:
            face_genuine.append(float(r.score))
    for split in ("attack_blur", "attack_side", "attack_replay_screen"):
        for p in sorted((data / "face" / split).glob("*.jpg")):
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            fm.inject_bgr(bgr)
            r = fm.capture_and_score()
            if r.score is not None:
                face_attack.append(float(r.score))

    # Combined trust-ish score for policy suggestion (static weights)
    from driveauth import config

    w_v, w_f = config.TRUST_W_VOICE, config.TRUST_W_FACE

    def fuse(vs, fs):
        out = []
        n = min(len(vs), len(fs)) if fs and vs else 0
        # Also report modality-only suggestions
        return out

    report = {
        "store": str(store),
        "voice": {
            "genuine": _summarize(voice_genuine),
            "attack": _summarize(voice_attack),
            "suggest_modality_bars": _suggest(voice_genuine, voice_attack),
        },
        "face": {
            "genuine": _summarize(face_genuine),
            "attack": _summarize(face_attack),
            "suggest_modality_bars": _suggest(face_genuine, face_attack),
        },
        "current_policy": {
            "TRUST_ACCEPT_MICRO": config.TRUST_ACCEPT_MICRO,
            "TRUST_ACCEPT_STD": config.TRUST_ACCEPT_STD,
            "TRUST_ACCEPT_HIGH": config.TRUST_ACCEPT_HIGH,
            "TRUST_REJECT": config.TRUST_REJECT,
            "LADDER_ACCEPT": config.LADDER_ACCEPT,
            "LADDER_ACCEPT_VOICE": config.LADDER_ACCEPT_VOICE,
            "LADDER_ACCEPT_FACE": config.LADDER_ACCEPT_FACE,
            "LADDER_ACCEPT_FINGER": config.LADDER_ACCEPT_FINGER,
            "weights": {"voice": w_v, "face": w_f, "finger": config.TRUST_W_FINGER},
        },
    }

    # Fused suggestion: weight genuine voice+face means as proxy for Trust
    # Use percentile mix: 0.3*voice_p15 + 0.4*face_p15 (finger absent)
    vg = report["voice"]["suggest_modality_bars"]
    fg = report["face"]["suggest_modality_bars"]

    # Ladder early-accept suggestions (prefer FAR=0; face stays strict if overlap).
    vl = (vg or {}).get("ladder") or {}
    fl = (fg or {}).get("ladder") or {}
    if vl or fl:
        voice_bar = float(vl.get("ladder_accept", config.LADDER_ACCEPT_VOICE))
        face_bar = float(fl.get("ladder_accept", config.LADDER_ACCEPT_FACE))
        # If face cannot accept any genuine at FAR=0, do not lower the bar.
        if float(fl.get("ladder_frr", 0.0)) >= 1.0 - 1e-9:
            face_bar = max(face_bar, float(config.LADDER_ACCEPT_FACE), 0.70)
        report["suggested_ladder"] = {
            "accept_voice": float(voice_bar),
            "accept_face": float(face_bar),
            "accept_finger": float(config.LADDER_ACCEPT_FINGER),
            "how": (
                "voice/face = lowest FAR=0 thr (ceiled 2-dp); face stays ≥0.70 if "
                "no genuine clears FAR=0; finger unchanged until FingerNet+HW"
            ),
        }

    if vg and fg:
        # Renormalize voice/face weights without finger
        s = w_v + w_f
        wv, wf = w_v / s, w_f / s
        fused_micro = wv * vg["accept_micro"] + wf * fg["accept_micro"]
        fused_std = wv * vg["accept_standard"] + wf * fg["accept_standard"]
        fused_high = wv * vg["accept_high"] + wf * fg["accept_high"]
        fused_rej = wv * vg["reject"] + wf * fg["reject"]
        report["suggested_policy_trust"] = {
            "accept_micro": round(float(fused_micro), 3),
            "accept_standard": round(float(fused_std), 3),
            "accept_high": round(float(fused_high), 3),
            "reject": round(float(fused_rej), 3),
            "how": "0.3/0.4 voice/face weight mix of modality percentile suggestions",
        }

    out = ROOT / "phases" / "phase2b_calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out}")

    if args.apply:
        env_path = ROOT / "phases" / "phase2b_suggested.env"
        lines: list[str] = []
        sug = report.get("suggested_policy_trust")
        if sug:
            lines.extend(
                [
                    f"export DRIVEAUTH_TRUST_ACCEPT_MICRO={sug['accept_micro']}",
                    f"export DRIVEAUTH_TRUST_ACCEPT_STD={sug['accept_standard']}",
                    f"export DRIVEAUTH_TRUST_ACCEPT_HIGH={sug['accept_high']}",
                    f"export DRIVEAUTH_TRUST_REJECT={sug['reject']}",
                ]
            )
        ladder = report.get("suggested_ladder")
        if ladder:
            lines.extend(
                [
                    f"export DRIVEAUTH_LADDER_ACCEPT_VOICE={ladder['accept_voice']}",
                    f"export DRIVEAUTH_LADDER_ACCEPT_FACE={ladder['accept_face']}",
                    f"export DRIVEAUTH_LADDER_ACCEPT_FINGER={ladder['accept_finger']}",
                ]
            )
        if lines:
            env_path.write_text("\n".join(lines) + "\n")
            print(f"Wrote {env_path} (source it to try; policy.yaml unchanged)")


if __name__ == "__main__":
    main()
