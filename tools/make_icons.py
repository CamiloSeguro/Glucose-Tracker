"""Generates the plugin icons in com.cgm.freestyle.sdPlugin/static/img.

Run from the repo root: python tools/make_icons.py
"""

import os

from PIL import Image, ImageDraw

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "com.cgm.freestyle.sdPlugin", "static", "img")
GREEN = (50, 190, 90)
BG    = (22, 22, 26)
LINE  = (240, 240, 240)
SS    = 8  # supersampling factor


def _drop(draw: ImageDraw.ImageDraw, cx: float, top: float, bottom: float, color):
    """Blood drop: circle at the bottom, pointed tip at the top."""
    r = (bottom - top) * 0.36
    cy = bottom - r
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    draw.polygon([(cx, top), (cx - r * 0.93, cy - r * 0.35), (cx + r * 0.93, cy - r * 0.35)], fill=color)


def icon(size: int, background: bool = True, color=GREEN) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=n * 0.22, fill=BG)
    _drop(d, n * 0.5, n * 0.14, n * 0.86, color)
    # CGM trace across the drop
    pts = [(0.30, 0.64), (0.42, 0.64), (0.48, 0.52), (0.56, 0.74), (0.62, 0.60), (0.70, 0.60)]
    d.line([(x * n, y * n) for x, y in pts], fill=LINE if background else (0, 0, 0, 0),
           width=max(1, int(n * 0.045)), joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = {
        "icon":     (72, True),   # plugin icon and default key image
        "category": (28, False),  # category list (monochrome-friendly)
        "action":   (20, False),  # action list
    }
    for name, (size, bg) in targets.items():
        color = GREEN if bg else (230, 230, 230)
        icon(size, bg, color).save(os.path.join(OUT_DIR, f"{name}.png"))
        icon(size * 2, bg, color).save(os.path.join(OUT_DIR, f"{name}@2x.png"))
    print(f"Icons written to {os.path.normpath(OUT_DIR)}")


if __name__ == "__main__":
    main()
