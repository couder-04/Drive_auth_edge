#!/usr/bin/env python3
"""Phase 2a — download pretrained models into a DriveAuth store.

Usage:
  python scripts/phase2a_setup.py --store ./driveauth_store_phase2a
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    urllib.request.urlretrieve(url, dest)
    print(f"  -> {dest} ({dest.stat().st_size // 1024} KB)")


def setup_ecapa(store: Path) -> None:
    print("\n[1/2] SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb)")
    savedir = store / "models" / "ecapa_voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)
    try:
        from driveauth.matchers.voice import VoiceMatcher

        VoiceMatcher.load_ecapa(savedir, device="cpu")
        print("  ECAPA ready at", savedir)
    except Exception as exc:
        print("  FAILED:", exc)
        print("  Install: pip install -e '.[voice]'")
        raise SystemExit(1) from exc


def setup_face_onnx(store: Path) -> Path:
    print("\n[2/2] ArcFace-MobileFaceNet ONNX")
    out = store / "models" / "mobilefacenet.onnx"
    if out.exists():
        print("  already present:", out)
        return out

    # Hailo model zoo hosts a pretrained ArcFace-MobileFaceNet ONNX.
    url = (
        "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/"
        "FaceRecognition/arcface/arcface_mobilefacenet/pretrained/"
        "2022-08-24/arcface_mobilefacenet.zip"
    )
    try:
        print("  downloading zip…")
        with urllib.request.urlopen(url, timeout=120) as resp:
            raw = resp.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            # Prefer *.onnx inside the archive
            onnx_names = [n for n in zf.namelist() if n.endswith(".onnx")]
            if not onnx_names:
                raise RuntimeError(f"no .onnx in zip; members={zf.namelist()[:10]}")
            member = onnx_names[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(member))
            print(f"  extracted {member} -> {out}")
            return out
    except Exception as exc:
        print("  Hailo download failed:", exc)
        print("  Fallback: place any 112x112 MobileFaceNet/ArcFace ONNX at:")
        print(f"    {out}")
        raise SystemExit(1) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2a pretrained model setup")
    parser.add_argument(
        "--store",
        default=str(ROOT / "driveauth_store_phase2a"),
        help="Store directory for models + templates",
    )
    parser.add_argument("--skip-voice", action="store_true")
    parser.add_argument("--skip-face", action="store_true")
    args = parser.parse_args()

    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    print("Phase 2a setup →", store.resolve())

    if not args.skip_voice:
        setup_ecapa(store)
    if not args.skip_face:
        setup_face_onnx(store)

    # Also symlink/copy face model to names FaceMatcher probes
    src = store / "models" / "mobilefacenet.onnx"
    if src.exists():
        for name in ("mobilefacenet.onnx", "mobilefacenet_int8.onnx"):
            dst = store / name
            if not dst.exists():
                dst.write_bytes(src.read_bytes())

    print("\nDone. Next:")
    print("  1. Capture Phase 3 samples into data/driver1/{voice,face}/enroll/")
    print(f"  2. python scripts/phase2a_enroll.py --store {store}")
    print(f"  3. python scripts/phase2a_demo.py --store {store}")


if __name__ == "__main__":
    main()
