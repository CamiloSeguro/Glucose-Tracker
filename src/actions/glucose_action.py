import base64
import io
import os
import threading
import time
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from librelinkup.client import AuthError, LibreLinkUpClient, RateLimitError, TermsError
from src.core.action import Action
from src.core.env import load_env
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

# After the API rejects the credentials, stop hammering the login endpoint:
# LibreLinkUp locks the account for 5 min after 3 failures.
AUTH_RETRY_S  = 30 * 60
STALE_AFTER_S = 15 * 60  # reading older than this is shown dimmed

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
        self._fetch_lock = threading.Lock()
        self._retry_at = 0.0       # no automatic API calls before this time
        self._locked_until = 0.0   # server lockout: not even a key press retries
        self._auth_failed = False  # credentials rejected: reload .env on key press

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def will_appear(self, settings: dict):
        self._start_client()
        # Don't block the WebSocket thread on the first network call
        threading.Thread(target=self._fetch_and_display, daemon=True).start()
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
        threading.Thread(target=self._manual_refresh, daemon=True).start()

    def _manual_refresh(self):
        if self._auth_failed:
            # Pick up a corrected password without restarting StreamDock
            load_env(override=True)
            with self._lock:
                self._client = None
            self._start_client()
        self._fetch_and_display(force=True)

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

    def _fetch_and_display(self, force: bool = False):
        # Timer and key press can overlap; the client is not thread-safe
        if not self._fetch_lock.acquire(blocking=False):
            return
        try:
            self._do_fetch(force)
        finally:
            self._fetch_lock.release()

    def _do_fetch(self, force: bool):
        with self._lock:
            client = self._client

        if client is None:
            self._show_error("Sin config")
            return

        now = time.time()
        if now < self._locked_until or (now < self._retry_at and not force):
            return

        try:
            reading = client.get_latest_glucose()
        except AuthError as e:
            Logger.error(f"LibreLinkUp: {e}. Fix LLU_PASSWORD in .env and press the button.")
            self._auth_failed = True
            self._retry_at = now + AUTH_RETRY_S
            self._show_error("Clave mala")
            return
        except RateLimitError as e:
            Logger.error(f"LibreLinkUp: {e}; retrying in {e.retry_after}s")
            self._locked_until = now + e.retry_after + 5
            self._show_error("Bloqueado")
            return
        except TermsError as e:
            Logger.error(f"LibreLinkUp: {e}")
            self._retry_at = now + AUTH_RETRY_S
            self._show_error("Acepta T&C")
            return
        except Exception as e:
            Logger.error(f"LibreLinkUp fetch error: {e}")
            self._show_error("Error API")
            return

        self._auth_failed = False
        self._retry_at = 0.0

        if reading is None:
            self._show_error("Sin datos")
            return

        value  = reading["value"]
        arrow  = reading["trend_arrow"]
        age_s  = _age_seconds(reading.get("measured_at"))
        if age_s is not None and age_s > STALE_AFTER_S:
            color = COLOR_DIM
            title = f"hace {int(age_s // 60)}m"
        else:
            color = _glucose_color(value, reading["is_low"], reading["is_high"])
            title = ""
        self.set_image(_make_button_image(value, arrow, color))
        self.set_title(title)
        Logger.info(f"Glucose updated: {value} mg/dL {arrow}" + (f" ({title})" if title else ""))

    def _show_error(self, msg: str):
        image = _make_button_image(None, "?", COLOR_BG)
        self.set_image(image)
        self.set_title(msg)


def _age_seconds(measured_at: datetime | None) -> float | None:
    if measured_at is None:
        return None
    return (datetime.now(timezone.utc) - measured_at).total_seconds()
