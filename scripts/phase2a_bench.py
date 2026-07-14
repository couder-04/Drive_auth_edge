#!/usr/bin/env python3
"""Phase 2a — ECAPA + MobileFaceNet latency profile (Mac or Thor).

Usage:
  python scripts/phase2a_bench.py --store ./driveauth_store_phase2a \\
      --out phases/phase2a-mac.txt

  # On Thor (CUDA EP when available):
  python scripts/phase2a_bench.py --store ./driveauth_store_phase2a \\
      --out phases/phase2a-thor.txt --device cuda

See phases/phase2a-thor.md for full onboard steps.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth import DriveAuth  # noqa: E402
from driveauth.matchers.face import FaceMatcher  # noqa: E402
from driveauth.matchers.mock import MockFaceMatcher, MockVoiceMatcher  # noqa: E402
from testsupport import mature  # noqa: E402

# Phase 2a interactive budget for real pretrained models (not Phase 1 mock).
REAL_AUTH_P95_MS = 200.0


def _percentile(times: list[float], p: float) -> float:
    if not times:
        return float("nan")
    s = sorted(times)
    idx = min(len(s) - 1, int(len(s) * p))
    return s[idx]


def _run_timed(fn, n: int, warmup: int = 3) -> list[float]:
    for _ in range(warmup):
        fn()
    out: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def _load_wav(path: Path) -> np.ndarray:
    import wave

    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            audio = audio.reshape(-1, 2).mean(axis=1)
    return audio


def _ort_info() -> str:
    try:
        import onnxruntime as ort

        return f"ORT {ort.__version__} providers={ort.get_available_providers()}"
    except Exception as exc:
        return f"ORT unavailable ({exc})"


def _nvidia() -> str:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = (out.stdout or out.stderr or "").strip()
        return text or "(nvidia-smi empty)"
    except Exception as exc:
        return f"(nvidia-smi: {exc})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2a latency bench")
    parser.add_argument("--store", default=str(ROOT / "driveauth_store_phase2a"))
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument("--out", default="", help="Profile path (default: stdout only)")
    parser.add_argument("--n", type=int, default=30, help="Timed iterations per case")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument(
        "--face-image",
        default=str(ROOT / "data" / "driver1" / "face" / "enroll" / "enroll_01.jpg"),
    )
    parser.add_argument(
        "--voice-wav",
        default=str(ROOT / "data" / "driver1" / "voice" / "enroll" / "enroll_01.wav"),
    )
    parser.add_argument(
        "--device",
        default="",
        help="Hint only (logged). Torch/ECAPA device is chosen by VoiceMatcher.",
    )
    args = parser.parse_args()

    os.environ["DRIVEAUTH_USE_MOCK"] = "0"
    os.environ["DRIVEAUTH_FINGERPRINT_AVAILABLE"] = "0"
    os.environ["DRIVEAUTH_STORE_DIR"] = args.store

    uname = platform.uname()
    store = Path(args.store)
    auth = DriveAuth.load(
        store_dir=str(store),
        enroll_dir=str(store / "enroll"),
        driver_id=args.driver_id,
        use_mock_matchers=False,
    )
    mature(auth)

    voice = auth._engine._m.voice
    face = auth._engine._m.face
    if isinstance(voice, MockVoiceMatcher) or isinstance(face, MockFaceMatcher):
        raise SystemExit(
            "FAIL: mock matchers loaded — install voice/face extras and re-run "
            "phase2a_setup / phase2a_enroll"
        )
    if not getattr(voice, "ready", False) or not getattr(face, "ready", False):
        raise SystemExit(
            f"FAIL: matchers not ready (voice.ready={getattr(voice, 'ready', None)} "
            f"face.ready={getattr(face, 'ready', None)}) — enroll first"
        )

    wav_path = Path(args.voice_wav)
    if not wav_path.is_file():
        raise SystemExit(f"missing voice wav: {wav_path}")
    audio = _load_wav(wav_path)

    face_path = Path(args.face_image)
    if not face_path.is_file():
        raise SystemExit(f"missing face image: {face_path}")
    import cv2

    bgr = cv2.imread(str(face_path))
    if bgr is None:
        raise SystemExit(f"cannot read face image: {face_path}")
    if isinstance(face, FaceMatcher):
        face.inject_bgr(bgr)

    # --- per-modality ---
    voice_ms = _run_timed(lambda: voice.score(audio), args.n, args.warmup)
    face_ms = _run_timed(lambda: face.capture_and_score(), args.n, args.warmup)

    def auth_voice_only():
        return auth.authenticate(
            audio_np=audio,
            amount=50.0,
            beneficiary="Starbucks",
            beneficiary_known=True,
            action="pay",
            currency="INR",
            channel="phase2a_bench",
            voice_expected=True,
        )

    def auth_high_value():
        # Force fuller probe set (high_value tier → voice+face at minimum).
        if isinstance(face, FaceMatcher):
            face.inject_bgr(bgr)
        return auth.authenticate(
            audio_np=audio,
            amount=50_000.0,
            beneficiary="NewVendor",
            beneficiary_known=False,
            action="pay",
            currency="INR",
            channel="phase2a_bench",
            voice_expected=True,
        )

    micro_ms = _run_timed(auth_voice_only, args.n, args.warmup)
    high_ms = _run_timed(auth_high_value, args.n, args.warmup)

    # One labeled result each for the profile header
    r_micro = auth_voice_only()
    if isinstance(face, FaceMatcher):
        face.inject_bgr(bgr)
    r_high = auth_high_value()

    v_p50, v_p95 = _percentile(voice_ms, 0.50), _percentile(voice_ms, 0.95)
    f_p50, f_p95 = _percentile(face_ms, 0.50), _percentile(face_ms, 0.95)
    m_p50, m_p95 = _percentile(micro_ms, 0.50), _percentile(micro_ms, 0.95)
    h_p50, h_p95 = _percentile(high_ms, 0.50), _percentile(high_ms, 0.95)

    budget_ok = m_p95 <= REAL_AUTH_P95_MS and h_p95 <= REAL_AUTH_P95_MS
    torch_dev = getattr(voice, "_device", "?")

    lines = [
        "Phase: 2a (pretrained ECAPA + MobileFaceNet latency)",
        f"Date: {date.today().isoformat()}",
        f"Status: {'PASS' if budget_ok else 'FAIL'} "
        f"(budget REAL_AUTH_P95_MS={REAL_AUTH_P95_MS:.0f})",
        "",
        f"Device: {uname.system} {uname.release} · {uname.machine} · node={uname.node}",
        f"Python: {sys.version.split()[0]}",
        f"Store: {store}",
        f"Device hint (--device): {args.device or '(none)'}",
        f"ECAPA torch device: {torch_dev}",
        "",
        "GPU / nvidia-smi:",
        _nvidia(),
        "",
        _ort_info(),
        "",
        "Models:",
        f"  Voice: {type(voice).__name__} ready={voice.ready}",
        f"  Face:  {type(face).__name__} ready={face.ready}",
        "  Finger / behavioral: mock (expected for 2a)",
        "",
        f"Inputs: voice={wav_path.name}  face={face_path.name}",
        f"Bench: n={args.n} warmup={args.warmup}",
        "",
        "Per-modality latency:",
        f"  ECAPA voice.score:     p50={v_p50:.1f}ms  p95={v_p95:.1f}ms  max={max(voice_ms):.1f}ms",
        f"  Face capture_and_score: p50={f_p50:.1f}ms  p95={f_p95:.1f}ms  max={max(face_ms):.1f}ms",
        "",
        "Full authenticate():",
        f"  Micro (early-stop voice): p50={m_p50:.1f}ms  p95={m_p95:.1f}ms  max={max(micro_ms):.1f}ms",
        f"    → {r_micro.decision.value}  trust={r_micro.trust_score:.3f}  "
        f"risk={r_micro.risk_score:.3f}  conf={r_micro.confidence_score:.3f}",
        f"  High-value (+face):       p50={h_p50:.1f}ms  p95={h_p95:.1f}ms  max={max(high_ms):.1f}ms",
        f"    → {r_high.decision.value}  trust={r_high.trust_score:.3f}  "
        f"risk={r_high.risk_score:.3f}  conf={r_high.confidence_score:.3f}",
        "",
        f"Latency budget: REAL_AUTH_P95_MS={REAL_AUTH_P95_MS:.0f} → "
        f"micro_p95={m_p95:.1f}ms high_p95={h_p95:.1f}ms "
        f"{'PASS' if budget_ok else 'FAIL'}",
        "  (compare Phase 1 mock: p50≈0.7ms)",
        "",
        "Compare: after Thor run, copy phases/phase2a-thor.txt beside this file.",
        "",
    ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}")
    if not budget_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
