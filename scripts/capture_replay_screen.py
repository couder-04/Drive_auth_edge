#!/usr/bin/env python3
"""Display enroll JPGs while capturing screen-replay face attacks.

Workflow: put the enroll window in front of the camera (phone Continuity Camera
aimed at this screen, or a second device photographing the laptop), then SPACE
to save into data/<driver>/face/attack_replay_screen/.

Usage (from repo root, with camera permission):
  .venv/bin/python scripts/capture_replay_screen.py --n 8
  .venv/bin/python scripts/capture_replay_screen.py --driver-id driver1 --camera 1
  .venv/bin/python scripts/capture_replay_screen.py --slideshow-only   # no camera
  # Point camera at a recorded slideshow video; snap every 2s (match --interval-ms):
  .venv/bin/python scripts/capture_replay_screen.py --from-recording --n 8 --interval-ms 2000

Keys (either window):
  SPACE     save camera frame as screen_XX.jpg (capture mode)
  n / →     next enroll photo
  p / ←     previous enroll photo
  f         toggle fullscreen on the enroll window
  q / Esc   quit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

ENROLL_WIN = "DriveAuth enroll replay (point camera here)"
CAMERA_WIN = "DriveAuth camera → attack_replay_screen"


def _next_index(directory: Path, prefix: str) -> int:
    nums: list[int] = []
    for path in directory.glob(f"{prefix}_*.jpg"):
        parts = path.stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            nums.append(int(parts[1]))
    return (max(nums) + 1) if nums else 1


def _load_enroll(enroll_dir: Path) -> list[Path]:
    paths = sorted(enroll_dir.glob("*.jpg"))
    if not paths:
        raise SystemExit(
            f"No enroll JPGs under {enroll_dir} — capture enroll first "
            "(scripts/capture_own_face.py --split enroll)"
        )
    return paths


def _fit_canvas(img: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    """Letterbox image onto a dark canvas of at most max_w x max_h."""
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1.0:
        img = cv2.resize(
            img,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
    h, w = img.shape[:2]
    canvas = np.zeros((max_h, max_w, 3), dtype=np.uint8)
    y0 = (max_h - h) // 2
    x0 = (max_w - w) // 2
    canvas[y0 : y0 + h, x0 : x0 + w] = img
    return canvas


def _annotate_enroll(
    canvas: np.ndarray,
    *,
    name: str,
    i: int,
    n_enroll: int,
    saved: int,
    need: int,
) -> np.ndarray:
    out = canvas.copy()
    cv2.putText(
        out,
        f"ENROLL {i + 1}/{n_enroll}  {name}  ·  replay saved {saved}/{need}",
        (24, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (40, 220, 120),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        out,
        "Point camera at THIS window  ·  SPACE=save  n/p=next/prev  f=fullscreen  q=quit",
        (24, 72),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (200, 200, 200),
        1,
        cv2.LINE_AA,
    )
    return out


def run_slideshow(
    face_root: Path,
    *,
    display_w: int,
    display_h: int,
    interval_ms: int,
) -> None:
    """Fullscreen-friendly enroll JPG slideshow (no camera)."""
    enroll_paths = _load_enroll(face_root / "enroll")
    enroll_i = 0
    fullscreen = False
    autoplay = interval_ms > 0

    print(f"Enroll slideshow → {face_root / 'enroll'}  ({len(enroll_paths)} JPGs)")
    print("Keys: n/p next/prev · SPACE next · f fullscreen · q quit")
    if autoplay:
        print(f"Auto-advance every {interval_ms} ms (SPACE still advances).")

    cv2.namedWindow(ENROLL_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(ENROLL_WIN, display_w, display_h)

    enroll_cache: dict[int, np.ndarray] = {}

    def enroll_frame(i: int) -> np.ndarray:
        if i not in enroll_cache:
            img = cv2.imread(str(enroll_paths[i]))
            if img is None:
                raise SystemExit(f"Cannot read {enroll_paths[i]}")
            enroll_cache[i] = img
        fitted = _fit_canvas(enroll_cache[i], display_w, display_h)
        return _annotate_enroll(
            fitted,
            name=enroll_paths[i].name,
            i=i,
            n_enroll=len(enroll_paths),
            saved=0,
            need=0,
        )

    wait = interval_ms if autoplay else 30
    try:
        while True:
            cv2.imshow(ENROLL_WIN, enroll_frame(enroll_i))
            key = cv2.waitKey(wait) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("n"), ord(" "), 83):
                enroll_i = (enroll_i + 1) % len(enroll_paths)
                print(f"  enroll → {enroll_paths[enroll_i].name}")
            elif key in (ord("p"), 81):
                enroll_i = (enroll_i - 1) % len(enroll_paths)
                print(f"  enroll → {enroll_paths[enroll_i].name}")
            elif key == ord("f"):
                fullscreen = not fullscreen
                prop = (
                    cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL
                )
                cv2.setWindowProperty(ENROLL_WIN, cv2.WND_PROP_FULLSCREEN, prop)
            elif autoplay and key == 255:
                # No key pressed — advance on interval.
                enroll_i = (enroll_i + 1) % len(enroll_paths)
                print(f"  enroll → {enroll_paths[enroll_i].name}")
    finally:
        cv2.destroyAllWindows()
    print("Slideshow closed")


def run_from_recording(
    face_root: Path,
    *,
    n: int,
    camera: int,
    interval_ms: int,
    countdown_s: float,
) -> None:
    """Camera-only: auto-save a frame every interval_ms (match slideshow rate)."""
    if interval_ms <= 0:
        raise SystemExit("--from-recording requires --interval-ms > 0 (e.g. 2000)")

    out_dir = face_root / "attack_replay_screen"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = "screen"

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(
            f"Cannot open camera index {camera}. Try --camera 1 (or Continuity Camera)."
        )

    saved = 0
    idx = _next_index(out_dir, prefix)
    interval_s = interval_ms / 1000.0

    print(f"Replay sink → {out_dir}")
    print(
        f"Timed capture: {n} frames every {interval_ms} ms "
        f"(same rate as slideshow). Starting at {prefix}_{idx:02d}.jpg"
    )
    print("Aim the camera at your playback of the slideshow recording.")
    if countdown_s > 0:
        print(f"Countdown {countdown_s:.0f}s — hit play so the first slide is showing.")

    cv2.namedWindow(CAMERA_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(CAMERA_WIN, 960, 720)

    t0 = time.monotonic()
    next_save_at: float | None = None
    try:
        while saved < n:
            ok, frame = cap.read()
            if not ok:
                print("Camera read failed")
                break

            now = time.monotonic()
            show = frame.copy()
            elapsed = now - t0

            if elapsed < countdown_s:
                left = countdown_s - elapsed
                label = f"START VIDEO — snapping in {left:0.1f}s  ({saved}/{n})"
                color = (40, 180, 255)
            else:
                if next_save_at is None:
                    next_save_at = now
                until = max(0.0, next_save_at - now)
                label = (
                    f"replay  {saved}/{n}  next snap in {until:0.1f}s  "
                    f"every {interval_ms}ms  q=quit"
                )
                color = (40, 220, 120)
                if now >= next_save_at:
                    path = out_dir / f"{prefix}_{idx:02d}.jpg"
                    cv2.imwrite(
                        str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]
                    )
                    print(f"  saved {path}")
                    saved += 1
                    idx += 1
                    next_save_at = now + interval_s

            cv2.putText(
                show,
                label,
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                color,
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(CAMERA_WIN, show)
            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    print(f"Done — saved {saved} into {out_dir}")


def run(
    face_root: Path,
    *,
    n: int,
    camera: int,
    display_w: int,
    display_h: int,
) -> None:
    enroll_paths = _load_enroll(face_root / "enroll")
    out_dir = face_root / "attack_replay_screen"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = "screen"

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(
            f"Cannot open camera index {camera}. Try --camera 1 (or Continuity Camera)."
        )

    saved = 0
    idx = _next_index(out_dir, prefix)
    enroll_i = 0
    fullscreen = False

    print(f"Enroll source → {face_root / 'enroll'}  ({len(enroll_paths)} JPGs)")
    print(f"Replay sink   → {out_dir}")
    print(f"Need {n} more (SPACE=save). Starting at {prefix}_{idx:02d}.jpg")
    print("Point the camera at the enroll window (screen presentation attack).")

    cv2.namedWindow(ENROLL_WIN, cv2.WINDOW_NORMAL)
    cv2.namedWindow(CAMERA_WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(ENROLL_WIN, display_w, display_h)
    cv2.resizeWindow(CAMERA_WIN, 640, 480)

    enroll_cache: dict[int, np.ndarray] = {}

    def enroll_frame(i: int) -> np.ndarray:
        if i not in enroll_cache:
            img = cv2.imread(str(enroll_paths[i]))
            if img is None:
                raise SystemExit(f"Cannot read {enroll_paths[i]}")
            enroll_cache[i] = img
        fitted = _fit_canvas(enroll_cache[i], display_w, display_h)
        return _annotate_enroll(
            fitted,
            name=enroll_paths[i].name,
            i=i,
            n_enroll=len(enroll_paths),
            saved=saved,
            need=n,
        )

    try:
        while saved < n:
            ok, frame = cap.read()
            if not ok:
                print("Camera read failed")
                break

            show_cam = frame.copy()
            cv2.putText(
                show_cam,
                f"replay  {saved}/{n}  SPACE=save  q=quit",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (40, 220, 120),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                show_cam,
                f"showing {enroll_paths[enroll_i].name}",
                (16, 62),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (200, 200, 200),
                1,
                cv2.LINE_AA,
            )

            cv2.imshow(ENROLL_WIN, enroll_frame(enroll_i))
            cv2.imshow(CAMERA_WIN, show_cam)

            key = cv2.waitKey(30) & 0xFF
            if key in (ord("q"), 27):
                break
            if key in (ord("n"), 83):  # n or right arrow
                enroll_i = (enroll_i + 1) % len(enroll_paths)
                print(f"  enroll → {enroll_paths[enroll_i].name}")
            elif key in (ord("p"), 81):  # p or left arrow
                enroll_i = (enroll_i - 1) % len(enroll_paths)
                print(f"  enroll → {enroll_paths[enroll_i].name}")
            elif key == ord("f"):
                fullscreen = not fullscreen
                prop = (
                    cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL
                )
                cv2.setWindowProperty(ENROLL_WIN, cv2.WND_PROP_FULLSCREEN, prop)
            elif key == ord(" "):
                path = out_dir / f"{prefix}_{idx:02d}.jpg"
                cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                print(
                    f"  saved {path}  (replay of {enroll_paths[enroll_i].name})"
                )
                saved += 1
                idx += 1
                # Advance enroll so each save tends to use a different source.
                enroll_i = (enroll_i + 1) % len(enroll_paths)
    finally:
        cap.release()
        cv2.destroyAllWindows()

    print(f"Done — saved {saved} into {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show enroll faces and capture screen-replay attacks"
    )
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--n", type=int, default=8, help="How many frames to capture")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument("--display-height", type=int, default=960)
    parser.add_argument(
        "--slideshow-only",
        action="store_true",
        help="Only show enroll JPGs (no camera / no saves)",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=0,
        help="Slideshow auto-advance / timed-capture interval (ms)",
    )
    parser.add_argument(
        "--from-recording",
        action="store_true",
        help="Camera-only timed snaps (point at playback of slideshow video)",
    )
    parser.add_argument(
        "--countdown",
        type=float,
        default=5.0,
        help="Seconds before first timed snap (--from-recording)",
    )
    args = parser.parse_args()

    face_root = args.data_root / args.driver_id / "face"
    if args.slideshow_only:
        run_slideshow(
            face_root,
            display_w=args.display_width,
            display_h=args.display_height,
            interval_ms=args.interval_ms,
        )
        return
    if args.from_recording:
        interval = args.interval_ms if args.interval_ms > 0 else 2000
        run_from_recording(
            face_root,
            n=args.n,
            camera=args.camera,
            interval_ms=interval,
            countdown_s=args.countdown,
        )
        return
    run(
        face_root,
        n=args.n,
        camera=args.camera,
        display_w=args.display_width,
        display_h=args.display_height,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
