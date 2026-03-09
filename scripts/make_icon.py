#!/usr/bin/env python3
"""Generate assets/icon.icns for KanadeMinder using Pillow + macOS iconutil."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow is required. Install with: uv run --with pillow python scripts/make_icon.py")
    sys.exit(1)

# Paths
REPO_ROOT = Path(__file__).parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
ICONSET_DIR = ASSETS_DIR / "KanadeMinder.iconset"
ICNS_PATH = ASSETS_DIR / "icon.icns"

# Icon design constants
BG_COLOR = (88, 86, 214, 255)   # #5856D6 — Apple-style indigo/purple
FG_COLOR = (255, 255, 255, 255)  # white text
CORNER_RADIUS_RATIO = 0.2224     # macOS icon squircle ratio

# Required iconset sizes: (filename_size, actual_px, scale)
ICON_SIZES = [
    (16,   16,   1),
    (16,   32,   2),
    (32,   32,   1),
    (32,   64,   2),
    (64,   64,   1),  # not required but included for completeness
    (128,  128,  1),
    (128,  256,  2),
    (256,  256,  1),
    (256,  512,  2),
    (512,  512,  1),
    (512,  1024, 2),
]


def rounded_rectangle(draw: ImageDraw.ImageDraw, xy: tuple, radius: int, fill: tuple) -> None:
    """Draw a rounded rectangle (squircle approximation)."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def make_icon(size: int) -> Image.Image:
    """Generate a single icon at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background: rounded square
    radius = int(size * CORNER_RADIUS_RATIO)
    rounded_rectangle(draw, (0, 0, size - 1, size - 1), radius=radius, fill=BG_COLOR)

    # Text: "KM" centered — skip for very small icons where text is unreadable
    if size < 32:
        return img

    text = "KM"
    font_size = max(8, int(size * 0.38))

    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    # Try system fonts in order of preference
    font_candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/SF-Pro-Display-Bold.otf",
    ]
    font = None
    for candidate in font_candidates:
        try:
            font = ImageFont.truetype(candidate, font_size, index=0)
            break
        except (OSError, IOError):
            continue

    if font is None:
        # Fall back to default bitmap font (small sizes only, acceptable fallback)
        font = ImageFont.load_default()

    # Center the text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2 - bbox[0]
    y = (size - text_h) // 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=FG_COLOR)

    return img


def build_iconset() -> None:
    """Build all required PNG files in KanadeMinder.iconset/."""
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    for name_size, px, scale in ICON_SIZES:
        img = make_icon(px)
        if scale == 1:
            filename = f"icon_{name_size}x{name_size}.png"
        else:
            filename = f"icon_{name_size}x{name_size}@2x.png"
        out_path = ICONSET_DIR / filename
        img.save(out_path, "PNG")
        print(f"  {filename} ({px}×{px})")


def run_iconutil() -> None:
    """Convert the iconset to .icns using macOS iconutil."""
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: iconutil failed:\n{result.stderr}")
        sys.exit(1)


def main() -> None:
    print(f"Building iconset in {ICONSET_DIR} ...")
    build_iconset()
    print(f"Running iconutil → {ICNS_PATH} ...")
    run_iconutil()
    print(f"Done: {ICNS_PATH}")


if __name__ == "__main__":
    main()
