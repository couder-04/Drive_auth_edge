#!/usr/bin/env python3
"""Capture dashboard ACCEPT → STEP_UP frames and write docs/demo.gif.

Prerequisites:
  - Dashboard running at http://127.0.0.1:8765
  - pip install pillow playwright && playwright install chromium

Usage:
  driveauth-dashboard   # separate terminal
  python scripts/capture_dashboard_demo_gif.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GIF = ROOT / "docs" / "demo.gif"
DEFAULT_FRAMES = ROOT / "docs" / "demo_frames"


def capture(url: str, out_dir: Path) -> list[tuple[Path, int]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: list[tuple[Path, int]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("#scenarios .scenario-btn")
        page.wait_for_timeout(400)

        idle = out_dir / "01_idle.png"
        page.screenshot(path=str(idle), full_page=False)
        shots.append((idle, 900))

        page.get_by_role("button", name="Micro payment (ACCEPT)").click()
        page.wait_for_function(
            "() => document.getElementById('decision-banner').textContent.trim() === 'ACCEPT'"
        )
        page.wait_for_timeout(350)
        accept = out_dir / "02_accept.png"
        page.screenshot(path=str(accept), full_page=False)
        shots.append((accept, 2200))

        page.get_by_role("button", name="High value (STEP_UP)").click()
        page.wait_for_function(
            "() => document.getElementById('decision-banner').textContent.trim() === 'STEP_UP_REQUIRED'"
        )
        page.wait_for_timeout(350)
        stepup = out_dir / "03_stepup.png"
        page.screenshot(path=str(stepup), full_page=False)
        shots.append((stepup, 2500))

        page.get_by_role("button", name="Micro payment (ACCEPT)").click()
        page.wait_for_function(
            "() => document.getElementById('decision-banner').textContent.trim() === 'ACCEPT'"
        )
        page.wait_for_timeout(250)
        accept2 = out_dir / "04_accept_again.png"
        page.screenshot(path=str(accept2), full_page=False)
        shots.append((accept2, 1400))

        browser.close()

    return shots


def build_gif(shots: list[tuple[Path, int]], gif_path: Path, *, width: int = 1200) -> None:
    frames: list[Image.Image] = []
    durations: list[int] = []
    for path, ms in shots:
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if w > width:
            im = im.resize((width, int(h * width / w)), Image.Resampling.LANCZOS)
        frames.append(im)
        durations.append(ms)

    quantized = [im.convert("P", palette=Image.ADAPTIVE, colors=128) for im in frames]
    gif_path.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        gif_path,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
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
    print(f"wrote {args.gif} ({size_kib:.0f} KiB)")

    if not args.keep_frames:
        for path, _ in shots:
            path.unlink(missing_ok=True)
        try:
            args.frames_dir.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
