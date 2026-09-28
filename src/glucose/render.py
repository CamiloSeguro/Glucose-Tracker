"""Button images. Everything is drawn at 2x (144 px) and downscaled for crisp edges."""

import base64
import io
import math
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

from src.glucose.settings import GlucoseSettings

S   = 144
OUT = 72

BG         = (14, 14, 16)
TEXT       = (240, 240, 240)
DIM        = (120, 120, 126)
BAND       = (32, 44, 36)     # target range behind the sparkline
URGENT_LOW = (255, 45, 45)
LOW        = (235, 85, 70)
IN_RANGE   = (50, 190, 90)
HIGH       = (240, 170, 30)
VERY_HIGH  = (255, 115, 40)

SPARK_HOURS = 3


def range_color(value: float | None, s: GlucoseSettings) -> tuple:
    if value is None:
        return DIM
    if value < s.urgent_low:
        return URGENT_LOW
    if value < s.low:
        return LOW
    if value > s.very_high:
        return VERY_HIGH
    if value > s.high:
        return HIGH
    return IN_RANGE


_font_cache: dict[tuple, ImageFont.ImageFont] = {}


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont:
    key = (size, bold)
    if key not in _font_cache:
        names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
        for name in names:
            try:
                _font_cache[key] = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int) -> ImageFont.ImageFont:
    size = start
    while size > 12:
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return _font(size)


def _encode(img: Image.Image) -> str:
    img = img.resize((OUT, OUT), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ----------------------------------------------------------------------
# Trend arrow (vector: fonts lack the diagonal arrows)
# ----------------------------------------------------------------------

# TrendArrow code -> (angle in degrees, 0 = right, counter-clockwise; double)
_TREND_GEOMETRY = {
    1: (90, True), 2: (90, False), 3: (45, False), 4: (0, False),
    5: (-45, False), 6: (-90, False), 7: (-90, True),
}


def _draw_arrow(draw: ImageDraw.ImageDraw, cx: float, cy: float, trend: int, color: tuple, size: float = 13):
    angle, double = _TREND_GEOMETRY.get(trend, (0, False))
    a = math.radians(angle)
    ux, uy = math.cos(a), -math.sin(a)   # screen y grows downwards
    px, py = -uy, ux

    def head(tipx, tipy):
        back = size * 0.75
        wing = size * 0.6
        draw.polygon([
            (tipx, tipy),
            (tipx - ux * back + px * wing, tipy - uy * back + py * wing),
            (tipx - ux * back - px * wing, tipy - uy * back - py * wing),
        ], fill=color)

    tail = (cx - ux * size, cy - uy * size)
    tip  = (cx + ux * size, cy + uy * size)
    draw.line([tail, (tip[0] - ux * size * 0.5, tip[1] - uy * size * 0.5)], fill=color, width=5)
    head(*tip)
    if double:
        head(tip[0] - ux * size * 0.7, tip[1] - uy * size * 0.7)


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

def _sparkline(draw: ImageDraw.ImageDraw, points: list[tuple[datetime, float]], now: datetime,
               s: GlucoseSettings, color: tuple, box: tuple[int, int, int, int]):
    x0, y0, x1, y1 = box
    start = now - timedelta(hours=SPARK_HOURS)
    pts = [(t, v) for t, v in points if t >= start]

    # Zoom to the data, but always keep the target band in view for context
    values = [v for _, v in pts]
    lo = min(values + [float(s.low)]) - 10
    hi = max(values + [float(s.high)]) + 10

    def y(v):
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    def x(t):
        return x0 + (t - start).total_seconds() / (SPARK_HOURS * 3600) * (x1 - x0)

    draw.rectangle([x0, y(s.high), x1, y(s.low)], fill=BAND)
    if len(pts) >= 2:
        coords = [(x(t), y(v)) for t, v in pts]
        draw.line(coords, fill=(170, 170, 176), width=3, joint="curve")
    if pts:
        cx, cy = x(pts[-1][0]), y(pts[-1][1])
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=color)


def glucose_image(value: float | None, trend: int, delta_text: str, history: list[tuple[datetime, float]],
                  now: datetime, s: GlucoseSettings, stale_text: str = "", inverted: bool = False) -> str:
    color = DIM if stale_text else range_color(value, s)
    bg, fg = (color, BG) if inverted else (BG, TEXT)

    img  = Image.new("RGB", (S, S), bg)
    draw = ImageDraw.Draw(img)

    # Value, colored by range
    text = s.format_value(value)
    font = _fit_font(draw, text, S - 16, 60)
    draw.text((S / 2, 44), text, font=font, fill=fg if inverted else color, anchor="mm")

    # Trend arrow + 5-min delta; a stale reading shows its age instead
    row_y = 86
    if stale_text:
        font = _fit_font(draw, stale_text, S - 16, 24)
        draw.text((S / 2, row_y), stale_text, font=font, fill=DIM, anchor="mm")
    else:
        label_font = _font(24)
        label_w = draw.textlength(delta_text, font=label_font) if delta_text else 0
        arrow_w = 30
        gap = 8 if delta_text else 0
        left = (S - arrow_w - gap - label_w) / 2
        _draw_arrow(draw, left + arrow_w / 2, row_y, trend, fg if inverted else color)
        if delta_text:
            draw.text((left + arrow_w + gap, row_y), delta_text, font=label_font,
                      fill=fg if inverted else TEXT, anchor="lm")

    if not inverted:
        _sparkline(draw, history, now, s, color, (10, 106, S - 10, S - 8))

    return _encode(img)


def detail_image(lines: list[tuple[str, int, tuple]]) -> str:
    """Stacked centered lines: (text, font size, color)."""
    img  = Image.new("RGB", (S, S), BG)
    draw = ImageDraw.Draw(img)
    heights = [size + 8 for _, size, _ in lines]
    y = (S - sum(heights)) / 2
    for (text, size, color), h in zip(lines, heights):
        font = _fit_font(draw, text, S - 12, size)
        draw.text((S / 2, y + h / 2), text, font=font, fill=color, anchor="mm")
        y += h
    return _encode(img)


def message_image(text: str, color: tuple = DIM) -> str:
    img  = Image.new("RGB", (S, S), BG)
    draw = ImageDraw.Draw(img)
    draw.ellipse([52, 18, 92, 58], outline=color, width=5)
    draw.text((S / 2, 38), "!", font=_font(28), fill=color, anchor="mm")
    lines = text.split("\n")
    y = 84 if len(lines) == 1 else 76
    for line in lines:
        font = _fit_font(draw, line, S - 12, 26)
        draw.text((S / 2, y), line, font=font, fill=TEXT, anchor="mm")
        y += 30
    return _encode(img)
