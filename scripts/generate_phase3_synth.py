#!/usr/bin/env python3
"""Generate synthetic Phase 3 finger / behavioral / OOD datasets.

No hardware required. Replace with real sensor / CAN / camera captures later;
keep folder names and CSV schema stable.

Usage:
  python scripts/generate_phase3_synth.py
  python scripts/generate_phase3_synth.py --seed 7 --skip-ood-voice
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "driver1"
KAGGLE_FACES = (
    Path.home()
    / ".cache/kagglehub/datasets/vasukipatel/face-recognition-dataset"
    / "versions/1/Faces/Faces"
)
CAN_COLS = [
    "t_ms",
    "steering_torque_nm",
    "brake_pressure_bar",
    "throttle_pct",
    "seat_pressure_kpa",
    "lateral_accel_g",
    "yaw_rate_dps",
    "vehicle_speed_kmh",
    "label",
]


def _clear_glob(folder: Path, pattern: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for p in folder.glob(pattern):
        p.unlink()


def _ridge_fingerprint(
    rng: np.random.Generator,
    *,
    size: int = 256,
    wet: bool = False,
    dry: bool = False,
    partial: bool = False,
    spoof: bool = False,
) -> np.ndarray:
    """Procedural ridge-like grayscale print (placeholder until real sensor)."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    cx, cy = size * 0.5 + rng.normal(0, 8), size * 0.45 + rng.normal(0, 8)
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    angle = np.arctan2(yy - cy, xx - cx)
    freq = 0.35 + float(rng.uniform(-0.05, 0.05))
    ridges = 0.5 + 0.5 * np.sin(rr * freq + angle * 3.0)
    ridges += 0.08 * rng.standard_normal((size, size))
    img = np.clip(ridges * 200 + 30, 0, 255).astype(np.uint8)
    # elliptical finger mask
    mask = ((xx - cx) / (size * 0.38)) ** 2 + ((yy - cy) / (size * 0.48)) ** 2 <= 1.0
    img = np.where(mask, img, 0).astype(np.uint8)
    if wet:
        img = cv2.GaussianBlur(img, (9, 9), 2.5)
        img = np.clip(img.astype(np.int16) + 40, 0, 255).astype(np.uint8)
    if dry:
        img = np.clip(img.astype(np.float32) * 0.55, 0, 255).astype(np.uint8)
        img = cv2.bilateralFilter(img, 5, 40, 40)
    if partial:
        cut = int(size * float(rng.uniform(0.35, 0.55)))
        img[:, cut:] = 0
    if spoof:
        # flat "print on paper" look: low contrast + grid
        img = cv2.GaussianBlur(img, (5, 5), 1.0)
        img = (img.astype(np.float32) * 0.7 + 40).clip(0, 255).astype(np.uint8)
        for y in range(0, size, 8):
            img[y, :] = np.clip(img[y, :].astype(np.int16) + 15, 0, 255)
    return img


def generate_finger(rng: np.random.Generator, out: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    enroll_dir = out / "enroll"
    genuine_dir = out / "genuine"
    attack_root = out / "attack"
    for d in (enroll_dir, genuine_dir):
        _clear_glob(d, "*.png")
    for tag in ("wrong", "partial", "wet", "dry", "spoof"):
        _clear_glob(attack_root / tag, "*.png")

    # Master ridge identity for enroll/genuine
    master_seed = int(rng.integers(0, 1_000_000))
    for i in range(1, 9):
        local = np.random.default_rng(master_seed + i)
        img = _ridge_fingerprint(local)
        path = enroll_dir / f"enroll_{i:02d}.png"
        cv2.imwrite(str(path), img)
        rows.append(
            {
                "path": str(path.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "finger",
                "split": "enroll",
                "notes": "synthetic ridge",
                "captured_at": now,
            }
        )
    for i in range(1, 21):
        local = np.random.default_rng(master_seed + 100 + i)
        img = _ridge_fingerprint(local)
        path = genuine_dir / f"genuine_{i:02d}.png"
        cv2.imwrite(str(path), img)
        rows.append(
            {
                "path": str(path.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "finger",
                "split": "genuine",
                "notes": "synthetic ridge",
                "captured_at": now,
            }
        )

    attack_specs = [
        ("wrong", dict()),  # different seed family
        ("partial", dict(partial=True)),
        ("wet", dict(wet=True)),
        ("dry", dict(dry=True)),
        ("spoof", dict(spoof=True)),
    ]
    for tag, kwargs in attack_specs:
        dest = attack_root / tag
        for i in range(1, 5):
            if tag == "wrong":
                local = np.random.default_rng(int(rng.integers(0, 1_000_000)) + i * 17)
            else:
                local = np.random.default_rng(master_seed + 500 + hash(tag) % 97 + i)
            img = _ridge_fingerprint(local, **kwargs)
            path = dest / f"{tag}_{i:02d}.png"
            cv2.imwrite(str(path), img)
            rows.append(
                {
                    "path": str(path.relative_to(ROOT / "data")),
                    "driver_id": "driver1",
                    "modality": "finger",
                    "split": f"attack_{tag}",
                    "notes": "synthetic",
                    "captured_at": now,
                }
            )

    (out / "SOURCE.txt").write_text(
        "Fingerprint Phase 3 — SYNTHETIC (pre-hardware)\n"
        "Generator: scripts/generate_phase3_synth.py\n"
        "enroll: 8  genuine: 20  attack: wrong/partial/wet/dry/spoof (4 each)\n"
        "Replace with real sensor captures when HW arrives; keep folder layout.\n"
        "Matcher stays mock until fingernet_lite_int8.onnx + sensor socket exist.\n"
    )
    return rows


def _can_window(
    rng: np.random.Generator,
    *,
    n: int,
    label: str,
    mode: str,
) -> list[dict[str, float | str | int]]:
    rows: list[dict[str, float | str | int]] = []
    speed = 40.0 if mode != "attack_idle_odd" else 5.0
    for t in range(n):
        if mode == "genuine":
            steer = float(rng.normal(0.0, 1.2))
            brake = max(0.0, float(rng.normal(0.3, 0.4)))
            throttle = float(np.clip(rng.normal(25.0, 8.0), 0, 80))
            seat = float(rng.normal(12.0, 0.4))
            lat = float(rng.normal(0.0, 0.05))
            yaw = float(rng.normal(0.0, 2.0))
            speed = float(np.clip(speed + rng.normal(0, 0.8), 0, 120))
        elif mode == "attack_aggressive":
            steer = float(rng.normal(0.0, 6.0))
            brake = float(np.clip(rng.normal(4.0, 2.0), 0, 12))
            throttle = float(np.clip(rng.normal(70.0, 15.0), 0, 100))
            seat = float(rng.normal(12.0, 1.5))
            lat = float(rng.normal(0.0, 0.35))
            yaw = float(rng.normal(0.0, 18.0))
            speed = float(np.clip(speed + rng.normal(2, 3), 0, 140))
        else:  # attack_idle_odd — brake+throttle both high
            steer = float(rng.normal(0.0, 0.5))
            brake = float(np.clip(rng.normal(6.0, 1.0), 0, 12))
            throttle = float(np.clip(rng.normal(55.0, 10.0), 0, 100))
            seat = float(rng.normal(3.0, 0.5))  # wrong seat profile
            lat = float(rng.normal(0.0, 0.02))
            yaw = float(rng.normal(0.0, 1.0))
            speed = float(np.clip(rng.normal(8.0, 4.0), 0, 40))
        rows.append(
            {
                "t_ms": t * 100,
                "steering_torque_nm": round(steer, 4),
                "brake_pressure_bar": round(brake, 4),
                "throttle_pct": round(throttle, 4),
                "seat_pressure_kpa": round(seat, 4),
                "lateral_accel_g": round(lat, 4),
                "yaw_rate_dps": round(yaw, 4),
                "vehicle_speed_kmh": round(speed, 4),
                "label": label,
            }
        )
    return rows


def generate_behavioral(rng: np.random.Generator, out: Path) -> list[dict[str, str]]:
    rows_m: list[dict[str, str]] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gen_dir = out / "genuine"
    atk_dir = out / "attack"
    _clear_glob(gen_dir, "*.csv")
    _clear_glob(atk_dir, "*.csv")

    for i in range(1, 21):
        path = gen_dir / f"can_{i:02d}.csv"
        window = _can_window(rng, n=50, label="genuine", mode="genuine")
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAN_COLS)
            w.writeheader()
            w.writerows(window)
        rows_m.append(
            {
                "path": str(path.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "behavioral",
                "split": "genuine",
                "notes": "synthetic CAN window n=50",
                "captured_at": now,
            }
        )

    for i, mode in enumerate(
        ["attack_aggressive"] * 4 + ["attack_idle_odd"] * 2, start=1
    ):
        path = atk_dir / f"can_{i:02d}.csv"
        window = _can_window(rng, n=50, label="attack", mode=mode)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAN_COLS)
            w.writeheader()
            w.writerows(window)
        rows_m.append(
            {
                "path": str(path.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "behavioral",
                "split": "attack",
                "notes": mode,
                "captured_at": now,
            }
        )

    (out / "SOURCE.txt").write_text(
        "Behavioral Phase 3 — SYNTHETIC CAN windows (pre-hardware)\n"
        "Schema matches BehavioralMonitor.update() keys + t_ms + label.\n"
        "genuine: 20 × 50 rows  attack: 6 × 50 rows\n"
        "Replace with real CAN recorder dumps when HW arrives.\n"
    )
    return rows_m


def generate_ood_face(out: Path, n: int = 20) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    face_dir = out / "face"
    _clear_glob(face_dir, "*.jpg")
    face_dir.mkdir(parents=True, exist_ok=True)

    src_files: list[Path] = []
    if KAGGLE_FACES.is_dir():
        # Prefer Brad Pitt (not RDJ enrolled identity)
        src_files = sorted(KAGGLE_FACES.glob("Brad Pitt_*.jpg"))[:n]
        if len(src_files) < n:
            src_files += [
                p
                for p in sorted(KAGGLE_FACES.glob("Tom Cruise_*.jpg"))
                if p not in src_files
            ][: n - len(src_files)]
    if len(src_files) < n:
        # Procedural fallback faces
        for i in range(len(src_files), n):
            img = np.full((160, 160, 3), 80, dtype=np.uint8)
            cv2.ellipse(img, (80, 80), (50, 65), 0, 0, 360, (160, 140, 120), -1)
            path = face_dir / f"ood_face_{i + 1:02d}.jpg"
            cv2.imwrite(str(path), img)
            rows.append(
                {
                    "path": str(path.relative_to(ROOT / "data")),
                    "driver_id": "driver1",
                    "modality": "ood_face",
                    "split": "ood",
                    "notes": "synthetic fallback face",
                    "captured_at": now,
                }
            )
        src_files = src_files  # copy remaining below

    for i, src in enumerate(src_files[:n], start=1):
        dest = face_dir / f"ood_face_{i:02d}.jpg"
        shutil.copy2(src, dest)
        rows.append(
            {
                "path": str(dest.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "ood_face",
                "split": "ood",
                "notes": f"kaggle other-id {src.name}",
                "captured_at": now,
            }
        )
    return rows


def generate_ood_finger(rng: np.random.Generator, out: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = out / "finger"
    _clear_glob(d, "*.png")
    for i in range(1, 6):
        local = np.random.default_rng(int(rng.integers(0, 1_000_000)) + i * 99)
        img = _ridge_fingerprint(local)
        path = d / f"ood_finger_{i:02d}.png"
        cv2.imwrite(str(path), img)
        rows.append(
            {
                "path": str(path.relative_to(ROOT / "data")),
                "driver_id": "driver1",
                "modality": "ood_finger",
                "split": "ood",
                "notes": "synthetic unknown print",
                "captured_at": now,
            }
        )
    return rows


def generate_ood_voice(out: Path, skip: bool) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = out / "voice"
    d.mkdir(parents=True, exist_ok=True)
    _clear_glob(d, "*.wav")
    if skip:
        (out / "SOURCE_voice.txt").write_text(
            "OOD voice skipped (--skip-ood-voice). Re-run without flag on Mac.\n"
        )
        return rows

    phrases = [
        "Pay Mom fifty",
        "Transfer two hundred to Raj",
        "Pay Uber eighty",
        "Authorize payment now",
        "Confirm transfer please",
    ]
    voices = ["Ralph", "Kathy", "Zarvox", "Trinoids", "Whisper"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_p = Path(tmp)
        for i, (voice, phrase) in enumerate(zip(voices, phrases), start=1):
            aiff = tmp_p / f"ood_{i}.aiff"
            wav = d / f"ood_voice_{i:02d}.wav"
            ok = subprocess.run(
                ["say", "-v", voice, "-o", str(aiff), phrase],
                capture_output=True,
            )
            if ok.returncode != 0:
                # fallback voice
                subprocess.run(
                    ["say", "-v", "Fred", "-o", str(aiff), phrase],
                    check=False,
                    capture_output=True,
                )
            if not aiff.exists():
                continue
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(aiff),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(wav),
                ],
                check=False,
                capture_output=True,
            )
            if wav.exists() and wav.stat().st_size > 100:
                rows.append(
                    {
                        "path": str(wav.relative_to(ROOT / "data")),
                        "driver_id": "driver1",
                        "modality": "ood_voice",
                        "split": "ood",
                        "notes": f"tts {voice}",
                        "captured_at": now,
                    }
                )
    return rows


def append_manifest(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
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
    parser = argparse.ArgumentParser(description="Generate synthetic Phase 3 datasets")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument(
        "--skip-ood-voice",
        action="store_true",
        help="Skip macOS say TTS for OOD voice",
    )
    args = parser.parse_args()
    rng = np.random.default_rng(args.seed)
    data = args.data

    print("Generating fingerprint…")
    m1 = generate_finger(rng, data / "finger")
    print("Generating behavioral CAN…")
    m2 = generate_behavioral(rng, data / "behavioral")
    print("Generating OOD faces / fingers…")
    ood = data / "ood"
    ood.mkdir(parents=True, exist_ok=True)
    m3 = generate_ood_face(ood)
    m4 = generate_ood_finger(rng, ood)
    print("Generating OOD voice…")
    m5 = generate_ood_voice(ood, skip=args.skip_ood_voice)

    (ood / "SOURCE.txt").write_text(
        "OOD Phase 3 negatives (not the enrolled driver)\n"
        "face: other Kaggle identity (or synthetic fallback)\n"
        "voice: macOS say TTS stand-ins\n"
        "finger: synthetic unknown prints\n"
        "Live OOD gating still uses store ood_stats/*.npz from enrollment.\n"
    )

    all_rows = m1 + m2 + m3 + m4 + m5
    append_manifest(all_rows)

    def count(p: Path, pat: str) -> int:
        return len(list(p.glob(pat))) if p.exists() else 0

    print("Done.")
    print(f"  finger enroll:   {count(data / 'finger' / 'enroll', '*.png')}")
    print(f"  finger genuine:  {count(data / 'finger' / 'genuine', '*.png')}")
    print(
        f"  finger attack:   {sum(count(data / 'finger' / 'attack' / t, '*.png') for t in ('wrong', 'partial', 'wet', 'dry', 'spoof'))}"
    )
    print(f"  behavioral gen:  {count(data / 'behavioral' / 'genuine', '*.csv')}")
    print(f"  behavioral atk:  {count(data / 'behavioral' / 'attack', '*.csv')}")
    print(f"  ood face:        {count(data / 'ood' / 'face', '*.jpg')}")
    print(f"  ood finger:      {count(data / 'ood' / 'finger', '*.png')}")
    print(f"  ood voice:       {count(data / 'ood' / 'voice', '*.wav')}")
    print(f"  manifest rows +: {len(all_rows)}")


if __name__ == "__main__":
    main()
