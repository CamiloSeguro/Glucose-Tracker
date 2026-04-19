import base64
import io
import os
import threading

from PIL import Image, ImageDraw, ImageFont

from librelinkup.client import LibreLinkUpClient
from src.core.action import Action
from src.core.logger import Logger

# Glucose thresholds (mg/dL)
LOW_THRESHOLD  = 70
HIGH_THRESHOLD = 180

# Colors (R, G, B)
COLOR_LOW    = (220, 60,  60)   # red
COLOR_HIGH   = (230, 160, 20)   # amber
COLOR_NORMAL = (50,  190, 90)   # green
COLOR_BG     = (15,  15,  15)   # near-black background
COLOR_TEXT   = (240, 240, 240)  # off-white
COLOR_DIM    = (120, 120, 120)  # muted gray

POLL_INTERVAL_MS = 60_000  # 60 s

SIZE = 144  # render 2x, downscale for crisp result


def _glucose_color(value: int | None, is_low: bool, is_high: bool) -> tuple:
    if value is None:
        return COLOR_DIM
    if is_low or value < LOW_THRESHOLD:
        return COLOR_LOW
    if is_high or value > HIGH_THRESHOLD:
        return COLOR_HIGH
    return COLOR_NORMAL


def _darken(color: tuple, factor: float = 0.35) -> tuple:
    return tuple(int(c * factor) for c in color)


def _make_button_image(value: int | None, trend_arrow: str, color: tuple) -> str:
    """Dark background + colored ring with glow, crisp 2x render."""
    S  = SIZE
    cx = S // 2

    img  = Image.new("RGB", (S, S), color=COLOR_BG)
    draw = ImageDraw.Draw(img)

    # ── Outer glow ring (wide, very dim) ─────────────────────────────
    glow = _darken(color, 0.25)
    draw.ellipse([6, 6, S - 6, S - 6], outline=glow, width=14)

    # ── Main colored ring ─────────────────────────────────────────────
    draw.ellipse([14, 14, S - 14, S - 14], outline=color, width=10)

    # ── Inner accent ring (thinner, slightly dim) ─────────────────────
    inner = _darken(color, 0.55)
    draw.ellipse([26, 26, S - 26, S - 26], outline=inner, width=3)

    # ── Fonts ─────────────────────────────────────────────────────────
    try:
        font_value = ImageFont.truetype("arialbd.ttf", 44)
        font_unit  = ImageFont.truetype("arial.ttf",   15)
        font_arrow = ImageFont.truetype("arialbd.ttf", 22)
    except OSError:
        font_value = ImageFont.load_default()
        font_unit  = font_value
        font_arrow = font_value

    value_text = str(value) if value is not None else "---"

    # ── Glucose number ────────────────────────────────────────────────
    draw.text((cx, 54), value_text, font=font_value, fill=COLOR_TEXT, anchor="mm")

    # ── Unit label ────────────────────────────────────────────────────
    draw.text((cx, 78), "mg/dL", font=font_unit, fill=COLOR_DIM, anchor="mm")

    # ── Trend arrow ───────────────────────────────────────────────────
    draw.text((cx, 100), trend_arrow, font=font_arrow, fill=color, anchor="mm")

    # ── Downscale to 72x72 with antialiasing ─────────────────────────
    img = img.resize((72, 72), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


class GlucoseAction(Action):
    def __init__(self, action: str, context: str, settings: dict, plugin):
        super().__init__(action, context, settings, plugin)
        self._client: LibreLinkUpClient | None = None
        self._timer_key: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def will_appear(self, settings: dict):
        self._start_client()
        self._fetch_and_display()
        self._timer_key = self.plugin.timer.set_interval(
            self._fetch_and_display, POLL_INTERVAL_MS
        )

    def will_disappear(self):
        if self._timer_key:
            self.plugin.timer.clear_interval(self._timer_key)
            self._timer_key = None

    # ------------------------------------------------------------------
    # Button press: refresh immediately
    # ------------------------------------------------------------------

    def key_up(self, payload: dict):
        threading.Thread(target=self._fetch_and_display, daemon=True).start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_client(self):
        email    = os.environ.get("LLU_EMAIL", "")
        password = os.environ.get("LLU_PASSWORD", "")
        if not email or not password:
            Logger.error("LLU_EMAIL / LLU_PASSWORD env vars not set")
            return
        with self._lock:
            if self._client is None:
                self._client = LibreLinkUpClient(email, password)

    def _fetch_and_display(self):
        with self._lock:
            client = self._client

        if client is None:
            self._show_error("Sin config")
            return

        try:
            reading = client.get_latest_glucose()
        except Exception as e:
            Logger.error(f"LibreLinkUp fetch error: {e}")
            self._show_error("Error API")
            return

        if reading is None:
            self._show_error("Sin datos")
            return

        value  = reading["value"]
        arrow  = reading["trend_arrow"]
        color  = _glucose_color(value, reading["is_low"], reading["is_high"])
        image  = _make_button_image(value, arrow, color)
        self.set_image(image)
        Logger.info(f"Glucose updated: {value} mg/dL {arrow}")

    def _show_error(self, msg: str):
        image = _make_button_image(None, "?", COLOR_BG)
        self.set_image(image)
        self.set_title(msg)
