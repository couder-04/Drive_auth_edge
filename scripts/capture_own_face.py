#!/usr/bin/env python3
"""Capture own-face enroll / genuine / attacks into data/<driver>/face/.

All splits use the same 640×480 close-up convention as dashboard /register
(enroll). Far-field 1080p genuines caused systemic Haar misses — do not vary
distance downward for the genuine split; vary light/expression only.

Usage (from repo root, with camera permission):
  .venv/bin/python scripts/capture_own_face.py --split enroll --n 8
  .venv/bin/python scripts/capture_own_face.py --split genuine --n 12
  .venv/bin/python scripts/capture_own_face.py --split attack_side --n 8
      # REAL profile / >45° turn — required for PAD (do NOT use geometric warps)
  .venv/bin/python scripts/capture_own_face.py --split attack_blur --n 8
      # live soft-focus / motion blur, or use --synth-attacks for a blur proxy
  .venv/bin/python scripts/capture_own_face.py --split attack_replay_screen --n 8
  .venv/bin/python scripts/capture_replay_screen.py --n 8   # enroll slideshow + camera
  .venv/bin/python scripts/capture_own_face.py --synth-attacks
      # Gaussian-blur proxy ONLY from enroll → attack_blur (OK for PAD).
      # Does NOT write attack_side — side-angle PA must be real camera captures.

Keys: SPACE = save · q / Esc = quit
"""

from __future__ import annotations

import argparse
import sys
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

SPLITS = {
    "enroll": ("enroll", "enroll"),
    "genuine": ("genuine", "genuine"),
    "attack_side": ("attack_side", "side"),
    "attack_blur": ("attack_blur", "blur"),
    "attack_replay_screen": ("attack_replay_screen", "screen"),
}

# Splits that must pass Haar + face_frac at save time (retake, don't discover later).
_REQUIRE_FACE = frozenset({"enroll", "genuine", "attack_blur", "attack_replay_screen"})

HINTS = {
    "enroll": "FRONTAL · good light · face LARGE in frame (fill guide oval)",
    "genuine": "Same close-up as enroll · frontal · vary light/expression only (NOT distance)",
    "attack_side": "Clear PROFILE / strong side turn (>45°) — face gate optional",
    "attack_blur": "Move during capture OR soft focus · still fill guide oval",
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
    """Gaussian-blur proxy for photo/screen/defocus presentation attacks.

    Legitimate PAD training proxy: output is genuinely blurry (unlike a
    perspective warp of live skin, which PAD correctly scores as bonafide).
    """
    img = cv2.imread(str(src))
    if img is None:
        raise RuntimeError(f"cannot read {src}")
    k = cv2.getGaussianKernel(31, 8.0)
    blurred = cv2.sepFilter2D(img, -1, k, k)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 90])


def synth_side_diagnostic_warp(
    src: Path, dest: Path, *, yaw_sign: float = 1.0
) -> Path:
    """Geometric yaw warp of a live frontal frame — NOT a presentation attack.

    Refuses destinations under ``attack_side/``. Kept for provenance MSE checks
    only — never feed these warps into PAD/calibrator attack classes.
    """
    dest = Path(dest)
    if "attack_side" in dest.parts:
        raise ValueError(
            f"refusing to write diagnostic warp into attack_side path: {dest}"
        )
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
    return dest


def synth_side(src: Path, dest: Path, *, yaw_sign: float = 1.0) -> Path:
    """Alias of :func:`synth_side_diagnostic_warp` (hard-guards ``attack_side/``)."""
    return synth_side_diagnostic_warp(src, dest, yaw_sign=yaw_sign)


def run_synth_attacks(face_root: Path) -> None:
    """Write ``attack_blur`` only (Gaussian proxy). Never writes ``attack_side``."""
    enroll = sorted((face_root / "enroll").glob("*.jpg"))
    if len(enroll) < 1:
        raise SystemExit(
            f"No enroll JPGs under {face_root / 'enroll'} — capture enroll first"
        )
    blur_dir = face_root / "attack_blur"
    blur_dir.mkdir(parents=True, exist_ok=True)
    for p in blur_dir.glob("*.jpg"):
        p.unlink()
    n = min(8, len(enroll))
    for i, src in enumerate(enroll[:n], start=1):
        synth_blur(src, blur_dir / f"blur_{i:02d}.jpg")
    print(f"Wrote {n} attack_blur images from enroll into {blur_dir}")
    print(
        "NOTE: --synth-attacks does NOT generate attack_side. "
        "Perspective warps of live enroll frames are not presentation attacks "
        "(PAD correctly treats them as bonafide). Capture real side-angle "
        "attacks with:  --split attack_side"
    )


def _open_capture(camera: int) -> cv2.VideoCapture:
    """Open camera at the shared enroll/genuine resolution (640×480)."""
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(
            f"Cannot open camera index {camera}. Try --camera 1 (or Continuity Camera)."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_FRAME_HEIGHT)
    return cap


def _draw_guide(show: np.ndarray, framing: dict, *, require_face: bool) -> None:
    h, w = show.shape[:2]
    # Guide oval ≈ face_frac 0.40 of frame height (enroll-like close-up).
    guide_h = int(0.40 * h)
    guide_w = int(guide_h * 0.85)
    cx, cy = w // 2, int(h * 0.45)
    color = (40, 220, 120) if framing.get("ok") else (40, 40, 220)
    if not require_face:
        color = (200, 180, 80)
    cv2.ellipse(show, (cx, cy), (guide_w // 2, guide_h // 2), 0, 0, 360, color, 2)
    box = framing.get("box")
    if box is not None:
        x, y, bw, bh = box
        cv2.rectangle(show, (x, y), (x + bw, y + bh), color, 2)
    frac = framing.get("face_frac")
    frac_s = f"{frac:.2f}" if frac is not None else "—"
    status = "OK" if framing.get("ok") else framing.get("reason", "no_face")
    cv2.putText(
        show,
        f"face_frac={frac_s}  min={config.FACE_MIN_FRAC:.2f}  {status}",
        (16, h - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )


def run_capture(
    face_root: Path,
    split: str,
    n: int,
    camera: int,
    *,
    allow_weak: bool = False,
    min_clean: int = 0,
) -> None:
    folder_name, prefix = SPLITS[split]
    out_dir = face_root / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = _open_capture(camera)
    require_face = split in _REQUIRE_FACE and not allow_weak

    saved = 0
    clean = 0  # Haar-confirmed (framing.ok) saves this session
    idx = _next_index(out_dir, prefix)
    print(f"Split={split}  → {out_dir}")
    print(f"Hint: {HINTS[split]}")
    print(
        f"Target resolution {CAPTURE_FRAME_WIDTH}×{CAPTURE_FRAME_HEIGHT} "
        f"(same as /register enroll)"
    )
    if require_face:
        print(
            f"Face gate ON — need Haar detect + face_frac≥{config.FACE_MIN_FRAC:.2f} "
            "(SPACE refused otherwise; --allow-weak to bypass)"
        )
    else:
        print("Face gate optional for this split (warn only)")
    if min_clean > 0:
        print(f"Session target: ≥{min_clean} Haar-confirmed (clean) saves")
    print(f"Need {n} more (SPACE=save, q=quit). Starting at {prefix}_{idx:02d}.jpg")

    win = "DriveAuth own-face capture"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while saved < n:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed")
            break
        # Enforce target size even if the camera ignored CAP_PROP_* requests.
        if frame.shape[1] != CAPTURE_FRAME_WIDTH or frame.shape[0] != CAPTURE_FRAME_HEIGHT:
            frame = cv2.resize(
                frame,
                (CAPTURE_FRAME_WIDTH, CAPTURE_FRAME_HEIGHT),
                interpolation=cv2.INTER_AREA,
            )
        framing = assess_face_framing(frame)
        show = frame.copy()
        _draw_guide(show, framing, require_face=require_face)
        frac = framing.get("face_frac")
        frac_s = f"{frac:.2f}" if frac is not None else "—"
        haar = "Haar OK" if framing.get("ok") else f"Haar FAIL ({framing.get('reason')})"
        cv2.putText(
            show,
            f"{split}  {saved}/{n}  clean={clean}"
            + (f"/{min_clean}" if min_clean > 0 else "")
            + "  SPACE=save  q=quit",
            (16, 32),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (40, 220, 120),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            show,
            f"live: {haar}  face_frac={frac_s}",
            (16, 62),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (40, 220, 120) if framing.get("ok") else (40, 40, 220),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            show,
            HINTS[split][:70],
            (16, 92),
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
            if require_face and not framing.get("ok"):
                print(
                    f"  refused — {framing.get('reason')} "
                    f"(face_frac={frac_s}; move closer / center face)"
                )
                continue
            if not framing.get("ok"):
                print(
                    f"  warning — {framing.get('reason')} "
                    f"(face_frac={frac_s}; saving anyway for {split})"
                )
            path = out_dir / f"{prefix}_{idx:02d}.jpg"
            cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            was_clean = bool(framing.get("ok"))
            if was_clean:
                clean += 1
            print(
                f"  saved {path.name}  face_frac={frac_s}  "
                f"haar={'OK' if was_clean else 'FAIL'}  "
                f"clean={clean}/{saved + 1}  "
                f"shape={frame.shape[1]}x{frame.shape[0]}"
            )
            saved += 1
            idx += 1

    cap.release()
    cv2.destroyAllWindows()
    print(
        f"Done — saved {saved} for {split} "
        f"({clean} Haar-confirmed / clean)"
    )
    if min_clean > 0 and clean < min_clean:
        raise SystemExit(
            f"Session ended with only {clean} clean (Haar-OK) captures; "
            f"need ≥{min_clean}. Re-run and hold face in the guide until live "
            f"face_frac clears, or lower --min-clean."
        )


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
        "--allow-weak",
        action="store_true",
        help="Skip capture-time face_frac gate (enroll/genuine normally require it)",
    )
    parser.add_argument(
        "--min-clean",
        type=int,
        default=0,
        help=(
            "Fail the session if fewer than N Haar-confirmed saves "
            "(0=off). Useful for enroll/genuine quality targets."
        ),
    )
    parser.add_argument(
        "--synth-attacks",
        action="store_true",
        help=(
            "Synthesize attack_blur only (Gaussian proxy from enroll). "
            "Does not write attack_side — use --split attack_side for real profiles"
        ),
    )
    args = parser.parse_args()

    face_root = args.data_root / args.driver_id / "face"
    face_root.mkdir(parents=True, exist_ok=True)

    if args.synth_attacks:
        run_synth_attacks(face_root)
        return

    if not args.split:
        raise SystemExit("Pass --split … or --synth-attacks")
    run_capture(
        face_root,
        args.split,
        args.n,
        args.camera,
        allow_weak=args.allow_weak,
        min_clean=args.min_clean,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
