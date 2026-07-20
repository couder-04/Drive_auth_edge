#!/usr/bin/env python3
"""Populate data/driver1/face from Kaggle vasukipatel face-recognition-dataset.

Selects Robert Downey Jr cropped faces by sharpness + eye-visibility,
copies enroll (8) + genuine (20), synthesizes attack_blur / attack_side.
"""

from __future__ import annotations

import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = Path.home() / (
    ".cache/kagglehub/datasets/vasukipatel/face-recognition-dataset"
    "/versions/1/Faces/Faces"
)
OUT = ROOT / "data" / "driver1" / "face"
IDENTITY = "Robert Downey Jr"
N_ENROLL = 8
N_GENUINE = 20
N_ATTACK_BLUR = 8
N_ATTACK_SIDE = 8


def _laplacian_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _eye_score(gray: np.ndarray) -> float:
    """Prefer images where Haar eye cascade finds 1–2 eyes in the upper face."""
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_eye.xml"
    if not cascade_path.exists():
        # Fallback: local contrast in upper-half eye band
        h, w = gray.shape
        band = gray[int(h * 0.25) : int(h * 0.55), :]
        return float(band.std()) / 64.0
    eyes = cv2.CascadeClassifier(str(cascade_path))
    h, w = gray.shape
    roi = gray[0 : int(h * 0.6), :]
    detected = eyes.detectMultiScale(roi, scaleFactor=1.1, minNeighbors=3, minSize=(12, 12))
    n = len(detected)
    if n == 0:
        return 0.0
    if n == 1:
        return 0.6
    if n == 2:
        return 1.0
    return 0.4  # too many detections → noisy


def _brightness_ok(gray: np.ndarray) -> bool:
    m = float(gray.mean())
    return 40.0 <= m <= 220.0


def rank_faces(src: Path) -> list[tuple[float, Path, float, float]]:
    files = sorted(src.glob(f"{IDENTITY}_*.jpg"))
    if not files:
        raise SystemExit(f"No {IDENTITY}_*.jpg under {src}")
    ranked: list[tuple[float, Path, float, float]] = []
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        if not _brightness_ok(img):
            continue
        sharp = _laplacian_var(img)
        eyes = _eye_score(img)
        # Sharpness primary; eye visibility as a tie-break bonus
        score = sharp * (0.55 + 0.45 * eyes)
        ranked.append((score, path, sharp, eyes))
    ranked.sort(key=lambda t: t[0], reverse=True)
    return ranked


def _clear_jpgs(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.glob("*.jpg"):
        p.unlink()
    for p in folder.glob("*.jpeg"):
        p.unlink()
    for p in folder.glob("*.png"):
        p.unlink()


def copy_split(paths: list[Path], dest: Path, prefix: str) -> list[Path]:
    _clear_jpgs(dest)
    out: list[Path] = []
    for i, src in enumerate(paths, start=1):
        dst = dest / f"{prefix}_{i:02d}.jpg"
        shutil.copy2(src, dst)
        out.append(dst)
    return out


def synth_blur(src: Path, dest: Path) -> Path:
    img = cv2.imread(str(src))
    if img is None:
        raise RuntimeError(f"cannot read {src}")
    # Heavy motion-ish blur (fails QualityGate / spoils matcher)
    k = cv2.getGaussianKernel(31, 8.0)
    blurred = cv2.sepFilter2D(img, -1, k, k)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), blurred, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return dest


def synth_side(src: Path, dest: Path, *, yaw_sign: float = 1.0) -> Path:
    """Cheap yaw/side-pose attack via perspective squeeze of one half."""
    img = cv2.imread(str(src))
    if img is None:
        raise RuntimeError(f"cannot read {src}")
    h, w = img.shape[:2]
    # Map rectangle → trapezoid (approximate >45° yaw)
    squeeze = 0.42
    if yaw_sign >= 0:
        src_pts = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
        dst_pts = np.float32(
            [
                [int(w * squeeze), 0],
                [w - 1, 0],
                [int(w * squeeze), h - 1],
                [w - 1, h - 1],
            ]
        )
    else:
        src_pts = np.float32([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]])
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


def write_manifest(rows: list[dict[str, str]]) -> None:
    path = ROOT / "data" / "manifest.csv"
    write_header = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["path", "driver_id", "modality", "split", "notes", "captured_at"],
        )
        if write_header:
            w.writeheader()
        w.writerows(rows)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    if not args.src.is_dir():
        raise SystemExit(
            f"Source not found: {args.src}\n"
            "Run: python -c \"import kagglehub; print(kagglehub.dataset_download("
            "'vasukipatel/face-recognition-dataset'))\""
        )

    ranked = rank_faces(args.src)
    need = N_ENROLL + N_GENUINE
    if len(ranked) < need:
        raise SystemExit(f"Only {len(ranked)} usable faces; need {need}")

    enroll_src = [p for _, p, _, _ in ranked[:N_ENROLL]]
    genuine_src = [p for _, p, _, _ in ranked[N_ENROLL : N_ENROLL + N_GENUINE]]

    enroll_out = copy_split(enroll_src, args.out / "enroll", "enroll")
    genuine_out = copy_split(genuine_src, args.out / "genuine", "genuine")

    # Attacks synthesized from top enroll frames (same identity, no genuine overlap)
    _clear_jpgs(args.out / "attack_blur")
    _clear_jpgs(args.out / "attack_side")
    blur_out: list[Path] = []
    side_out: list[Path] = []
    for i, src in enumerate(enroll_src[:N_ATTACK_BLUR], start=1):
        blur_out.append(synth_blur(src, args.out / "attack_blur" / f"blur_{i:02d}.jpg"))
    for i, src in enumerate(enroll_src[:N_ATTACK_SIDE], start=1):
        sign = 1.0 if i % 2 else -1.0
        side_out.append(
            synth_side(src, args.out / "attack_side" / f"side_{i:02d}.jpg", yaw_sign=sign)
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_rows: list[dict[str, str]] = []
    for p in enroll_out:
        manifest_rows.append(
            {
                "path": str(p.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "face",
                "split": "enroll",
                "notes": f"{IDENTITY}; sharpness+eyes ranked",
                "captured_at": now,
            }
        )
    for p in genuine_out:
        manifest_rows.append(
            {
                "path": str(p.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "face",
                "split": "genuine",
                "notes": f"{IDENTITY}; next-best after enroll",
                "captured_at": now,
            }
        )
    for p in blur_out:
        manifest_rows.append(
            {
                "path": str(p.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "face",
                "split": "attack_blur",
                "notes": f"{IDENTITY}; gaussian blur of enroll",
                "captured_at": now,
            }
        )
    for p in side_out:
        manifest_rows.append(
            {
                "path": str(p.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "face",
                "split": "attack_side",
                "notes": f"{IDENTITY}; perspective yaw of enroll",
                "captured_at": now,
            }
        )
    write_manifest(manifest_rows)

    # SOURCE.txt provenance
    lines = [
        "Face data from Kaggle vasukipatel/face-recognition-dataset",
        f"Identity: {IDENTITY} (same person for enroll + genuine + attacks)",
        f"Source: {args.src}",
        f"enroll: {N_ENROLL} best sharpness/eye-visible",
        f"genuine: {N_GENUINE} next-best same identity (no overlap with enroll)",
        f"attack_side / attack_blur: synthesized from enroll frames "
        f"({N_ATTACK_SIDE} side / {N_ATTACK_BLUR} blur)",
        "",
        "Selected source files (score desc):",
    ]
    for i, (score, path, sharp, eyes) in enumerate(ranked[:need], start=1):
        split = "enroll" if i <= N_ENROLL else "genuine"
        lines.append(
            f"  [{split:7}] {path.name}  score={score:.1f}  "
            f"sharp={sharp:.1f}  eyes={eyes:.2f}"
        )
    (args.out / "SOURCE.txt").write_text("\n".join(lines) + "\n")

    print(f"enroll:       {len(enroll_out)}")
    print(f"genuine:      {len(genuine_out)}")
    print(f"attack_blur:  {len(blur_out)}")
    print(f"attack_side:  {len(side_out)}")
    print("SOURCE.txt + manifest.csv updated")


if __name__ == "__main__":
    main()
