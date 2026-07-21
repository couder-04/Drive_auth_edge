#!/usr/bin/env python3
"""Auto-recapture driver1 genuine face (+ optional voice) at enroll framing.

Designed for Terminal.app / iTerm (macOS camera+mic TCC), not the Cursor agent
sandbox — those processes usually lack AVFoundation access.

Face: opens 640×480, waits for Haar+face_frac gate, then auto-saves with a
short cooldown so you can vary expression/angle between shots.

Voice: records N clips via ffmpeg avfoundation (16 kHz mono WAV).

Usage (from repo root, in Terminal.app):
  source .venv/bin/activate && set -a && source secrets.env && set +a
  python scripts/recapture_driver1_genuine.py --face-n 22
  python scripts/recapture_driver1_genuine.py --voice-n 24 --skip-face
  python scripts/recapture_driver1_genuine.py --face-n 22 --voice-n 24
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driveauth import config  # noqa: E402
from driveauth.matchers.face import (  # noqa: E402
    CAPTURE_FRAME_HEIGHT,
    CAPTURE_FRAME_WIDTH,
    assess_face_framing,
)
from driveauth.quality_gate import score_voice  # noqa: E402


def _backup_dir(src: Path) -> Path | None:
    files = sorted(src.glob("*"))
    files = [p for p in files if p.is_file() and p.name != ".gitkeep"]
    if not files:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = src.parent / f"{src.name}_backup_{stamp}"
    dest.mkdir(parents=True, exist_ok=False)
    for p in files:
        shutil.copy2(p, dest / p.name)
    for p in files:
        p.unlink()
    print(f"Backed up {len(files)} files → {dest}")
    return dest


def _open_cam(camera: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(
            f"Cannot open camera {camera}. Grant Camera access to Terminal/iTerm "
            "in System Settings → Privacy & Security → Camera, then retry."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_FRAME_HEIGHT)
    return cap


def capture_faces(
    out_dir: Path,
    *,
    n: int,
    camera: int,
    cooldown_s: float,
    hold_s: float,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _backup_dir(out_dir)
    cap = _open_cam(camera)
    saved: list[dict] = []
    idx = 1
    last_save = 0.0
    hold_ok_since: float | None = None
    win = "DriveAuth genuine re-capture (auto)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    print(
        f"Face auto-capture: need {n} Haar-OK frames at "
        f"{CAPTURE_FRAME_WIDTH}×{CAPTURE_FRAME_HEIGHT}, "
        f"face_frac≥{config.FACE_MIN_FRAC:.2f}. q=quit."
    )
    print("Fill the green oval; hold steady — saves automatically.")

    while len(saved) < n:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed")
            break
        if (
            frame.shape[1] != CAPTURE_FRAME_WIDTH
            or frame.shape[0] != CAPTURE_FRAME_HEIGHT
        ):
            frame = cv2.resize(
                frame,
                (CAPTURE_FRAME_WIDTH, CAPTURE_FRAME_HEIGHT),
                interpolation=cv2.INTER_AREA,
            )
        framing = assess_face_framing(frame)
        show = frame.copy()
        h, w = show.shape[:2]
        guide_h = int(0.40 * h)
        guide_w = int(guide_h * 0.85)
        color = (40, 220, 120) if framing.get("ok") else (40, 40, 220)
        cv2.ellipse(
            show,
            (w // 2, int(h * 0.45)),
            (guide_w // 2, guide_h // 2),
            0,
            0,
            360,
            color,
            2,
        )
        box = framing.get("box")
        if box is not None:
            x, y, bw, bh = box
            cv2.rectangle(show, (x, y), (x + bw, y + bh), color, 2)
        frac = framing.get("face_frac")
        frac_s = f"{frac:.2f}" if frac is not None else "—"
        now = time.time()
        status = framing.get("reason", "?")
        if framing.get("ok"):
            if hold_ok_since is None:
                hold_ok_since = now
            held = now - hold_ok_since
            status = f"HOLD {held:.1f}/{hold_s:.1f}s"
            if held >= hold_s and (now - last_save) >= cooldown_s:
                path = out_dir / f"genuine_{idx:02d}.jpg"
                cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                row = {
                    "path": str(path),
                    "face_frac": float(frac),
                    "shape": [int(frame.shape[1]), int(frame.shape[0])],
                    "fallback": False,
                }
                saved.append(row)
                print(
                    f"  saved {path.name}  face_frac={frac:.3f}  "
                    f"shape={frame.shape[1]}x{frame.shape[0]}  ({len(saved)}/{n})"
                )
                idx += 1
                last_save = now
                hold_ok_since = None
        else:
            hold_ok_since = None

        cv2.putText(
            show,
            f"genuine auto  {len(saved)}/{n}  q=quit",
            (16, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (40, 220, 120),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            show,
            f"face_frac={frac_s}  {status}",
            (16, h - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
        cv2.imshow(win, show)
        if (cv2.waitKey(30) & 0xFF) in (ord("q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()
    return saved


def _ffmpeg_audio_device() -> str:
    """Return first AVFoundation audio device index as string."""
    proc = subprocess.run(
        ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
    )
    lines = (proc.stderr or "").splitlines()
    in_audio = False
    for line in lines:
        if "AVFoundation audio devices" in line:
            in_audio = True
            continue
        if in_audio and "AVFoundation video devices" in line:
            break
        if in_audio:
            # e.g. [AVFoundation ...] [0] MacBook Pro Microphone
            if "] [" in line:
                try:
                    idx = line.split("] [", 1)[1].split("]", 1)[0]
                    int(idx)
                    return idx
                except Exception:
                    continue
    return "0"


def capture_voices(
    out_dir: Path,
    *,
    n: int,
    seconds: float,
    phrases: list[str],
) -> list[dict]:
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found — brew install ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    _backup_dir(out_dir)
    adev = _ffmpeg_audio_device()
    print(f"Voice capture via ffmpeg avfoundation audio device [{adev}]")
    print(f"Need {n} clips × {seconds:.1f}s. Press Enter before each clip.")
    rows: list[dict] = []
    for i in range(1, n + 1):
        phrase = phrases[(i - 1) % len(phrases)]
        path = out_dir / f"genuine_{i:02d}.wav"
        input(f"\n[{i}/{n}] Say: “{phrase}” — Enter to start recording… ")
        print(f"  Recording {seconds:.1f}s …")
        # ":none" video + audio device; 16 kHz mono pcm_s16le
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "avfoundation",
            "-i",
            f":{adev}",
            "-t",
            str(seconds),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not path.is_file():
            print(proc.stderr[-800:] if proc.stderr else "ffmpeg failed")
            raise SystemExit(f"ffmpeg failed for {path.name}")
        audio = _load_wav_mono(path)
        ok, q, notes = score_voice(audio)
        row = {
            "path": str(path),
            "duration_s": float(audio.size / 16_000),
            "quality_ok": bool(ok),
            "quality": float(q),
            "notes": list(notes),
            "phrase": phrase,
        }
        rows.append(row)
        print(
            f"  saved {path.name}  dur={row['duration_s']:.2f}s  "
            f"q_ok={ok}  q={q:.3f}  notes={notes}"
        )
    return rows


def _load_wav_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16_000
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


PHRASES = [
    "pay Mom fifty",
    "transfer two hundred to Raj",
    "open navigation",
    "pay Starbucks one fifty",
    "confirm payment now",
    "send five thousand home",
    "unlock the cabin",
    "authorize this purchase",
]


def verify_faces(out_dir: Path) -> dict:
    rows = []
    for p in sorted(out_dir.glob("genuine_*.jpg")):
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        fr = assess_face_framing(bgr)
        rows.append(
            {
                "file": p.name,
                "ok": bool(fr.get("ok")),
                "face_frac": fr.get("face_frac"),
                "reason": fr.get("reason"),
                "shape": [int(bgr.shape[1]), int(bgr.shape[0])],
            }
        )
    n_ok = sum(1 for r in rows if r["ok"])
    return {
        "n": len(rows),
        "haar_ok": n_ok,
        "hit_rate": n_ok / max(len(rows), 1),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--driver-id", default="driver1")
    ap.add_argument("--data-root", type=Path, default=ROOT / "data")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--face-n", type=int, default=22)
    ap.add_argument("--voice-n", type=int, default=24)
    ap.add_argument("--voice-seconds", type=float, default=3.5)
    ap.add_argument("--skip-face", action="store_true")
    ap.add_argument("--skip-voice", action="store_true")
    ap.add_argument("--cooldown", type=float, default=1.2)
    ap.add_argument("--hold", type=float, default=0.6)
    args = ap.parse_args()

    face_dir = args.data_root / args.driver_id / "face" / "genuine"
    voice_dir = args.data_root / args.driver_id / "voice" / "genuine"

    if not args.skip_face:
        saved = capture_faces(
            face_dir,
            n=args.face_n,
            camera=args.camera,
            cooldown_s=args.cooldown,
            hold_s=args.hold,
        )
        ver = verify_faces(face_dir)
        print(
            f"\nFace verify: Haar hit-rate {ver['haar_ok']}/{ver['n']} "
            f"= {ver['hit_rate']:.1%}"
        )
        if ver["hit_rate"] < 0.95:
            print("WARNING: hit-rate < 95% — re-run face capture before training")
        if len(saved) < args.face_n:
            print(f"WARNING: only saved {len(saved)}/{args.face_n} faces")

    if not args.skip_voice:
        rows = capture_voices(
            voice_dir,
            n=args.voice_n,
            seconds=args.voice_seconds,
            phrases=PHRASES,
        )
        ok_n = sum(1 for r in rows if r["quality_ok"])
        print(f"\nVoice quality_ok: {ok_n}/{len(rows)}")
        sample = rows[:5]
        print("sample score_voice():")
        for r in sample:
            print(
                f"  {Path(r['path']).name}: ok={r['quality_ok']} "
                f"q={r['quality']:.3f} dur={r['duration_s']:.2f} notes={r['notes']}"
            )

    print("\nDone. Next: retrain Stage-2 heads, then audit_driver1_e2e.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
