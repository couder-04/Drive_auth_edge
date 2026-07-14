#!/usr/bin/env python3
"""Capture own-face enroll / genuine / attacks into data/<driver>/face/.

Usage (from repo root, with camera permission):
  .venv/bin/python scripts/capture_own_face.py --split enroll --n 8
  .venv/bin/python scripts/capture_own_face.py --split genuine --n 12
  .venv/bin/python scripts/capture_own_face.py --split attack_side --n 8
  .venv/bin/python scripts/capture_own_face.py --split attack_replay_screen --n 8
  .venv/bin/python scripts/capture_replay_screen.py --n 8   # enroll slideshow + camera
  .venv/bin/python scripts/capture_own_face.py --synth-attacks   # blur+side from enroll

Keys: SPACE = save · q / Esc = quit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

SPLITS = {
    "enroll": ("enroll", "enroll"),
    "genuine": ("genuine", "genuine"),
    "attack_side": ("attack_side", "side"),
    "attack_blur": ("attack_blur", "blur"),
    "attack_replay_screen": ("attack_replay_screen", "screen"),
}

HINTS = {
    "enroll": "FRONTAL · good light · face large · slight expression/tilt OK",
    "genuine": "Still mostly frontal · vary light / distance / expression",
    "attack_side": "Clear PROFILE / strong side turn (>45°)",
    "attack_blur": "Move during capture OR soft focus",
    "attack_replay_screen": "Show your face on a phone/laptop screen, photo that screen",
}


def _next_index(directory: Path, prefix: str) -> int:
    nums: list[int] = []
    for path in directory.glob(f"{prefix}_*.jpg"):
        parts = path.stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            nums.append(int(parts[1]))
    return (max(nums) + 1) if nums else 1


def synth_blur(src: Path, dest: Path) -> None:
    img = cv2.imread(str(src))
    if img is None:
        raise RuntimeError(f"cannot read {src}")
    k = cv2.getGaussianKernel(31, 8.0)
    blurred = cv2.sepFilter2D(img, -1, k, k)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 90])


def synth_side(src: Path, dest: Path, *, yaw_sign: float = 1.0) -> None:
    img = cv2.imread(str(src))
    if img is None:
        raise RuntimeError(f"cannot read {src}")
    h, w = img.shape[:2]
    squeeze = 0.42
    src_pts = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
    if yaw_sign >= 0:
        dst_pts = np.float32(
            [
                [int(w * squeeze), 0],
                [w - 1, 0],
                [int(w * squeeze), h - 1],
                [w - 1, h - 1],
            ]
        )
    else:
        dst_pts = np.float32(
            [
                [0, 0],
                [int(w * (1.0 - squeeze)), 0],
                [0, h - 1],
                [int(w * (1.0 - squeeze)), h - 1],
            ]
        )
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), warped, [int(cv2.IMWRITE_JPEG_QUALITY), 90])


def run_synth_attacks(face_root: Path) -> None:
    enroll = sorted((face_root / "enroll").glob("*.jpg"))
    if len(enroll) < 1:
        raise SystemExit(
            f"No enroll JPGs under {face_root / 'enroll'} — capture enroll first"
        )
    blur_dir = face_root / "attack_blur"
    side_dir = face_root / "attack_side"
    blur_dir.mkdir(parents=True, exist_ok=True)
    side_dir.mkdir(parents=True, exist_ok=True)
    for p in blur_dir.glob("*.jpg"):
        p.unlink()
    for p in side_dir.glob("*.jpg"):
        p.unlink()
    n = min(8, len(enroll))
    for i, src in enumerate(enroll[:n], start=1):
        synth_blur(src, blur_dir / f"blur_{i:02d}.jpg")
        sign = 1.0 if i % 2 else -1.0
        synth_side(src, side_dir / f"side_{i:02d}.jpg", yaw_sign=sign)
    print(f"Wrote {n} blur + {n} side attacks from enroll into {face_root}")


def run_capture(face_root: Path, split: str, n: int, camera: int) -> None:
    folder_name, prefix = SPLITS[split]
    out_dir = face_root / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(
            f"Cannot open camera index {camera}. Try --camera 1 (or Continuity Camera)."
        )

    saved = 0
    idx = _next_index(out_dir, prefix)
    print(f"Split={split}  → {out_dir}")
    print(f"Hint: {HINTS[split]}")
    print(f"Need {n} more (SPACE=save, q=quit). Starting at {prefix}_{idx:02d}.jpg")

    win = "DriveAuth own-face capture"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while saved < n:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed")
            break
        show = frame.copy()
        cv2.putText(
            show,
            f"{split}  {saved}/{n}  SPACE=save  q=quit",
            (16, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (40, 220, 120),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            show,
            HINTS[split][:70],
            (16, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )
        cv2.imshow(win, show)
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord(" "):
            path = out_dir / f"{prefix}_{idx:02d}.jpg"
            cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            print(f"  saved {path}")
            saved += 1
            idx += 1

    cap.release()
    cv2.destroyAllWindows()
    print(f"Done — saved {saved} for {split}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture own-face samples")
    parser.add_argument("--driver-id", default="driver1")
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--split",
        choices=list(SPLITS),
        help="Which folder to write into",
    )
    parser.add_argument("--n", type=int, default=8, help="How many frames to capture")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument(
        "--synth-attacks",
        action="store_true",
        help="Synthesize attack_blur + attack_side from existing enroll JPGs",
    )
    args = parser.parse_args()

    face_root = args.data_root / args.driver_id / "face"
    face_root.mkdir(parents=True, exist_ok=True)

    if args.synth_attacks:
        run_synth_attacks(face_root)
        return

    if not args.split:
        raise SystemExit("Pass --split … or --synth-attacks")
    run_capture(face_root, args.split, args.n, args.camera)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
