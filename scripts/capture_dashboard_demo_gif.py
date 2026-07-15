#!/usr/bin/env python3
"""Capture dashboard ladder demo frames and write docs/demo.gif.

Story (matches README):
  Micro payment → ACCEPT
  Low voice → Face ACCEPT
  Low biometrics → REJECT

Prerequisites:
  - Dashboard running at http://127.0.0.1:8765
  - pip install pillow playwright && playwright install chromium

Usage:
  driveauth-dashboard   # separate terminal
  python scripts/capture_dashboard_demo_gif.py
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GIF = ROOT / "docs" / "demo.gif"
DEFAULT_FRAMES = ROOT / "docs" / "demo_frames"

# README demo story — button labels must match /api/scenarios.
SCENES: list[tuple[str, str, int]] = [
    ("Micro payment (ACCEPT)", "ACCEPT", 2400),
    ("Low voice → Face ACCEPT", "ACCEPT", 2600),
    ("Low biometrics (REJECT after ladder)", "REJECT", 2800),
]


def _caption_font(size: int = 22) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _annotate(im: Image.Image, text: str) -> Image.Image:
    """Bottom caption bar — keeps the RESULT decision banner visible at top."""
    out = im.copy()
    draw = ImageDraw.Draw(out)
    font = _caption_font(20)
    pad_x, pad_y = 14, 10
    bbox = draw.textbbox((0, 0), text, font=font)
    th = bbox[3] - bbox[1]
    bar_h = th + pad_y * 2
    y0 = out.height - bar_h
    draw.rectangle((0, y0, out.width, out.height), fill=(8, 14, 28))
    draw.rectangle((0, y0, out.width, y0 + 2), fill=(56, 189, 248))
    draw.text((pad_x, y0 + pad_y - 1), text, fill=(226, 232, 240), font=font)
    brand = "DriveAuth Edge"
    bb = draw.textbbox((0, 0), brand, font=font)
    bw = bb[2] - bb[0]
    draw.text(
        (out.width - bw - pad_x, y0 + pad_y - 1),
        brand,
        fill=(148, 163, 184),
        font=font,
    )
    return out


def _wait_idle(page) -> None:
    page.wait_for_function(
        """() => {
          const pill = document.getElementById('live-pill');
          if (!pill) return false;
          return !pill.classList.contains('running');
        }""",
        timeout=20_000,
    )
    page.wait_for_timeout(200)


def _shot(page, path: Path) -> None:
    # Skip brand header / nav; keep Result decision banner + escalation staircase.
    page.screenshot(path=str(path), full_page=False, clip={
        "x": 0, "y": 88, "width": 1440, "height": 780,
    })


def capture(url: str, out_dir: Path) -> list[tuple[Path, int]]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: list[tuple[Path, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#scenarios .scenario-btn")
        page.wait_for_timeout(500)

        idle = out_dir / "00_idle.png"
        _shot(page, idle)
        _annotate(Image.open(idle).convert("RGB"), "Presets · Voice → Face → Finger").save(idle)
        shots.append((idle, 1100))

        for i, (label, expect, hold_ms) in enumerate(SCENES, start=1):
            # Mid-run frame while staircase is climbing
            page.get_by_role("button", name=label, exact=True).click()
            page.wait_for_function(
                "() => document.getElementById('live-pill')?.classList.contains('running')",
                timeout=10_000,
            )
            # Let Voice rung enter "probing" before mid-frame.
            page.wait_for_timeout(520)
            mid = out_dir / f"{i:02d}a_climbing.png"
            _shot(page, mid)
            shots.append((mid, 700))

            page.wait_for_function(
                f"() => {{ const t = document.getElementById('decision-banner'); "
                f"return t && t.textContent.trim() === {expect!r}; }}",
                timeout=20_000,
            )
            _wait_idle(page)
            page.wait_for_timeout(280)
            final = out_dir / f"{i:02d}b_{re.sub(r'[^a-z0-9]+', '_', expect.lower()).strip('_')}.png"
            _shot(page, final)
            short = label.split("(")[0].strip()
            captioned = out_dir / f"{i:02d}c_captioned.png"
            _annotate(Image.open(final).convert("RGB"), f"{short}  →  {expect}").save(captioned)
            # Replace raw final with captioned hold; keep mid without caption
            shots.append((captioned, hold_ms))

        browser.close()

    return shots


def build_gif(shots: list[tuple[Path, int]], gif_path: Path, *, width: int = 1080) -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for path, ms in shots:
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, int(h * width / w)), Image.Resampling.LANCZOS)
        frames.append(im)
        durations.append(ms)

    # Shared adaptive palette across frames reduces flicker vs per-frame convert.
    master = Image.new("RGB", frames[0].size)
    # collage a few frames for a stable palette
    step = max(1, len(frames) // 4)
    for i, fr in enumerate(frames[::step]):
        master.paste(fr, (0, 0))
    palette_img = master.quantize(colors=160, method=Image.Quantize.MEDIANCUT)

    quantized: list[Image.Image] = []
    for fr in frames:
        q = fr.quantize(palette=palette_img, dither=Image.Dither.NONE)
        quantized.append(q)

    gif_path.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        gif_path,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    parser.add_argument("--gif", type=Path, default=DEFAULT_GIF)
    parser.add_argument("--frames-dir", type=Path, default=DEFAULT_FRAMES)
    parser.add_argument("--keep-frames", action="store_true")
    args = parser.parse_args()

    shots = capture(args.url, args.frames_dir)
    build_gif(shots, args.gif)
    size_kib = args.gif.stat().st_size / 1024
    print(f"wrote {args.gif} ({size_kib:.0f} KiB, {len(shots)} frames)")

    if not args.keep_frames:
        shutil.rmtree(args.frames_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
