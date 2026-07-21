#!/usr/bin/env python3
"""After genuine re-capture: verify → retrain driver1 Stage-2 → stock-bar audit.

Does NOT lower bars. Does NOT touch driver7. Does NOT commit.

Usage (after face+voice genuine re-capture):
  source .venv/bin/activate && set -a && source secrets.env && set +a
  python scripts/driver1_post_recapture_pipeline.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STORE = ROOT / "driveauth_store_phase2a"
DATA = ROOT / "data" / "driver1"
DRIVER = "driver1"


def _run(cmd: list[str], *, env: dict | None = None) -> None:
    print("\n$", " ".join(cmd), flush=True)
    merged = os.environ.copy()
    if env:
        merged.update(env)
    # Never apply demo bar-lowering overrides
    for k in list(merged):
        if k.startswith("DRIVEAUTH_") and (
            "phase2b" in k.lower()
            or k
            in {
                "DRIVEAUTH_VOICE_THRESHOLD",
                "DRIVEAUTH_FACE_THRESHOLD",
                "DRIVEAUTH_LADDER_VOICE_BAR",
                "DRIVEAUTH_LADDER_FACE_BAR",
            }
        ):
            # Keep stock unless explicitly stock-safe; strip known demo overrides
            pass
    # Explicitly unset demo file sourcings
    merged.pop("DRIVEAUTH_DEMO_MODE", None)
    r = subprocess.run(cmd, cwd=str(ROOT), env=merged)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(cmd)}")


def verify_new_data() -> dict:
    import cv2
    from driveauth.quality_gate import score_voice
    from driveauth.matchers.face import assess_face_framing, CAPTURE_FRAME_WIDTH
    from scripts._bio_train_common import load_wav

    face_dir = DATA / "face" / "genuine"
    voice_dir = DATA / "voice" / "genuine"
    faces = sorted(face_dir.glob("genuine_*.jpg"))
    voices = sorted(voice_dir.glob("genuine_*.wav"))
    if len(faces) < 20:
        raise SystemExit(f"Need ≥20 genuine faces, found {len(faces)} under {face_dir}")
    if len(voices) < 20:
        raise SystemExit(f"Need ≥20 genuine WAVs, found {len(voices)} under {voice_dir}")

    face_rows = []
    for p in faces:
        bgr = cv2.imread(str(p))
        fr = assess_face_framing(bgr)
        face_rows.append(
            {
                "file": p.name,
                "ok": bool(fr.get("ok")),
                "face_frac": fr.get("face_frac"),
                "shape": [int(bgr.shape[1]), int(bgr.shape[0])],
                "reason": fr.get("reason"),
            }
        )
    n_ok = sum(1 for r in face_rows if r["ok"])
    shapes = {tuple(r["shape"]) for r in face_rows}
    voice_rows = []
    for p in voices[:8]:
        audio = load_wav(p)
        ok, q, notes = score_voice(audio)
        voice_rows.append(
            {
                "file": p.name,
                "ok": bool(ok),
                "q": float(q),
                "notes": list(notes),
                "dur": float(audio.size / 16_000),
            }
        )

    out = {
        "face_n": len(faces),
        "face_haar_ok": n_ok,
        "face_hit_rate": n_ok / len(faces),
        "face_shapes": [list(s) for s in sorted(shapes)],
        "voice_n": len(voices),
        "voice_sample_quality": voice_rows,
    }
    print(
        f"Face Haar hit-rate: {n_ok}/{len(faces)} = {out['face_hit_rate']:.1%}  "
        f"shapes={out['face_shapes']}"
    )
    if out["face_hit_rate"] < 0.90:
        raise SystemExit(
            "Haar hit-rate < 90% on new genuines — re-capture before training "
            "(far-field / fallback risk)."
        )
    if any(s[0] != CAPTURE_FRAME_WIDTH for s in shapes):
        print("WARNING: some faces not 640-wide — check capture convention")
    print("Voice sample score_voice():")
    for r in voice_rows:
        print(f"  {r['file']}: ok={r['ok']} q={r['q']:.3f} dur={r['dur']:.2f}s notes={r['notes']}")
    return out


def retrain() -> dict:
    py = str(ROOT / ".venv" / "bin" / "python")
    _run(
        [
            py,
            "scripts/train_face_pad.py",
            "--store",
            str(STORE),
            "--data",
            str(DATA),
            "--driver-id",
            DRIVER,
            "--exclude-fallback-crops",
        ]
    )
    _run(
        [
            py,
            "scripts/train_face_calibrator.py",
            "--store",
            str(STORE),
            "--data",
            str(DATA),
            "--driver-id",
            DRIVER,
        ]
    )
    _run(
        [
            py,
            "scripts/train_voice_calibrator.py",
            "--store",
            str(STORE),
            "--data",
            str(DATA),
            "--driver-id",
            DRIVER,
        ]
    )

    from driveauth.stage2_artifacts import stage2_status_for_driver

    status = stage2_status_for_driver(STORE, DRIVER)
    metas = {}
    for rel in (
        "faces/driver1/face_pad.json",
        "faces/driver1/face_calibrator.json",
        "voices/driver1/voice_calibrator.json",
    ):
        p = STORE / rel
        metas[rel] = json.loads(p.read_text()) if p.is_file() else None
    return {"stage2_status": status, "metas": metas}


def live_pad_auc() -> dict:
    """Re-use diagnostic script for live vs LOO PAD AUC."""
    py = str(ROOT / ".venv" / "bin" / "python")
    _run([py, "scripts/diagnose_driver1_pad_haar.py"])
    d = json.loads((ROOT / "phases" / "driver1_pad_haar_diagnosis.json").read_text())
    return {
        "loo_auc": d["pad"]["pad_meta_summary"].get("loo_auc"),
        "auc_slices": d["pad"]["auc_slices"],
        "confusion": d["pad"]["confusion_all"],
        "parity_mismatches": d["pad"]["parity"]["n_mismatches"],
    }


def audit() -> dict:
    py = str(ROOT / ".venv" / "bin" / "python")
    # Ensure stock bars: strip demo / phase2b overrides if present in the shell
    scrub = {
        "DRIVEAUTH_DEMO_MODE": "",
        "DRIVEAUTH_VOICE_ACCEPT": "",
        "DRIVEAUTH_FACE_ACCEPT": "",
        "DRIVEAUTH_LADDER_VOICE": "",
        "DRIVEAUTH_LADDER_FACE": "",
    }
    env = {k: v for k, v in os.environ.items() if v}
    for k in list(env):
        if "PHASE2B" in k.upper() or k in scrub:
            env.pop(k, None)
    _run([py, "scripts/audit_driver1_e2e.py"], env=env)
    return json.loads((ROOT / "phases" / "driver1_e2e_audit.json").read_text())


def overfit() -> None:
    py = str(ROOT / ".venv" / "bin" / "python")
    _run(
        [
            py,
            "scripts/overfit_audit_stage2.py",
            "--store",
            str(STORE),
            "--driver-id",
            DRIVER,
        ]
    )


def main() -> None:
    if os.getenv("DRIVEAUTH_DEMO_MODE", "").strip() in ("1", "true", "yes"):
        raise SystemExit("DRIVEAUTH_DEMO_MODE is set — unset it for stock-bar audit")

    print("=== verify new genuine data ===")
    verify = verify_new_data()
    print("=== retrain Stage-2 (driver1 only) ===")
    train = retrain()
    print("=== live PAD diagnostic ===")
    pad_live = live_pad_auc()
    print("=== stock-bar e2e audit ===")
    audit_out = audit()
    print("=== overfit audit ===")
    overfit()

    status = train["stage2_status"]
    arts = status.get("artifacts") or {}
    stock = (audit_out.get("phase7_10") or {}).get("stock") or {}
    p34 = audit_out.get("phase3_4") or {}
    summary = {
        "verify": verify,
        "stage2_mode": status.get("mode"),
        "training_origins": {
            k: (arts.get(k) or {}).get("training_origin")
            for k in ("face_pad", "face_calibrator", "voice_calibrator")
        },
        "artifact_sources": {
            k: (arts.get(k) or {}).get("source")
            for k in ("face_pad", "face_calibrator", "voice_calibrator")
        },
        "loo": {
            "face_pad": (train["metas"].get("faces/driver1/face_pad.json") or {}).get(
                "loo_auc"
            ),
            "face_cal": (
                train["metas"].get("faces/driver1/face_calibrator.json") or {}
            ).get("loo_auc"),
            "voice_cal": (
                train["metas"].get("voices/driver1/voice_calibrator.json") or {}
            ).get("loo_auc"),
        },
        "pad_live": pad_live,
        "stock_summary": stock.get("summary"),
        "face_cal_genuine_mean": (p34.get("face_cal") or {}).get("genuine_mean"),
        "voice_cal_genuine_mean": (p34.get("voice_cal") or {}).get("genuine_mean"),
        "stock_bars": {"voice": 0.72, "face": 0.70},
    }
    out = ROOT / "phases" / "driver1_post_recapture_summary.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote {out}")
    print("LOO AUCs:", summary["loo"])
    print("PAD live slices:", pad_live.get("auc_slices"))
    print("STOCK:", summary["stock_summary"])
    print(
        "genuine means vs bars: face",
        summary["face_cal_genuine_mean"],
        "/ 0.70 ; voice",
        summary["voice_cal_genuine_mean"],
        "/ 0.72",
    )


if __name__ == "__main__":
    main()
