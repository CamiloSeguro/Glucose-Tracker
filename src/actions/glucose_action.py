import threading
import time
from datetime import datetime, timedelta, timezone

from src.core.action import Action
from src.core.logger import Logger
from src.glucose import render
from src.glucose.history import time_in_range
from src.glucose.service import STALE_AFTER_S, Snapshot, get_service

LONG_PRESS_S = 0.6
DETAIL_S     = 6
BLINK_MS     = 800

ERROR_COLORS = {"Clave mala": render.LOW, "Bloqueado": render.HIGH, "Acepta T&C": render.HIGH}


class GlucoseAction(Action):
    def __init__(self, action: str, context: str, settings: dict, plugin):
        super().__init__(action, context, settings, plugin)
        self._service = get_service(plugin)
        self._snapshot: Snapshot | None = None
        self._render_lock = threading.Lock()
        self._key_down_at = 0.0
        self._detail_until = 0.0
        self._blink_key: str | None = None
        self._blink_on = False

    @property
    def patient_id(self) -> str | None:
        return self.settings.get("patientId") or None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def will_appear(self, settings: dict):
        self._service.subscribe(self)

    def will_disappear(self):
        self._service.unsubscribe(self)
        self._set_blinking(False)

    def did_receive_settings(self, settings: dict):
        # Patient changed: drop the old reading and fetch the new one
        self._snapshot = None
        self._service.refresh(force=True)

    # ------------------------------------------------------------------
    # Keys: short press refreshes, long press shows today's summary
    # ------------------------------------------------------------------

    def key_down(self, payload: dict):
        self._key_down_at = time.time()

    def key_up(self, payload: dict):
        held = time.time() - self._key_down_at if self._key_down_at else 0
        self._key_down_at = 0.0
        if held >= LONG_PRESS_S and self._snapshot and not self._snapshot.error:
            self._show_detail()
        else:
            self._service.refresh(force=True)

    def _show_detail(self):
        self._detail_until = time.time() + DETAIL_S
        self.set_image(self._detail_image(self._snapshot))
        threading.Timer(DETAIL_S + 0.1, self._render).start()

    # ------------------------------------------------------------------
    # Settings panel
    # ------------------------------------------------------------------

    def property_inspector_did_appear(self, payload: dict):
        self._send_state()

    def send_to_plugin(self, payload: dict):
        event = payload.get("event")
        if event == "saveCredentials":
            self._service.save_credentials(payload.get("email", ""), payload.get("password", ""))
            # Report the login result once the polling thread has tried it
            threading.Timer(4, self._send_state).start()
        elif event == "saveSettings":
            self._service.save_settings(payload.get("settings", {}))
        elif event == "getPatients":
            self._service.run_task(self._send_patients)
        self._send_state()

    def _send_state(self):
        self.send_to_property_inspector({"event": "state", **self._service.public_state()})

    def _send_patients(self, client):
        try:
            patients = client.get_patients() if client else []
        except Exception as e:
            Logger.error(f"Could not list patients: {e}")
            patients = []
        self.send_to_property_inspector({"event": "patients", "patients": patients})

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def on_snapshot(self, snap: Snapshot):
        self._snapshot = snap
        self._set_blinking(snap.alert == "urgent_low")
        self._render()

    def _render(self):
        snap = self._snapshot
        if snap is None or time.time() < self._detail_until:
            return
        with self._render_lock:
            if snap.error:
                self.set_image(render.message_image(snap.error, ERROR_COLORS.get(snap.error, render.DIM)))
            else:
                self.set_image(self._glucose_image(snap, inverted=self._blink_on))
            self.set_title("")

    def _glucose_image(self, snap: Snapshot, inverted: bool = False) -> str:
        s   = self._service.settings
        now = datetime.now(timezone.utc)
        stale = ""
        if snap.measured_at:
            age = (now - snap.measured_at).total_seconds()
            if age > STALE_AFTER_S:
                stale = f"hace {int(age // 60)}m" if age < 3600 else f"hace {int(age // 3600)}h"
        return render.glucose_image(
            snap.value, snap.trend, s.format_delta(snap.delta), snap.history, now, s,
            stale_text=stale, inverted=inverted,
        )

    def _detail_image(self, snap: Snapshot) -> str:
        s   = self._service.settings
        now = datetime.now(timezone.utc)
        tir = time_in_range(snap.history, s)
        last3h = [v for t, v in snap.history if t >= now - timedelta(hours=3)] or [snap.value]

        if tir is None:
            tir_text, tir_color = "--", render.DIM
        else:
            tir_text = f"{round(tir * 100)}%"
            tir_color = render.IN_RANGE if tir >= 0.7 else render.HIGH if tir >= 0.5 else render.LOW

        age = ""
        if snap.measured_at:
            minutes = int((now - snap.measured_at).total_seconds() // 60)
            age = "ahora" if minutes < 1 else f"hace {minutes}m"

        return render.detail_image([
            ("12h en rango", 18, render.DIM),
            (tir_text, 44, tir_color),
            (f"3h  {s.format_value(min(last3h))}–{s.format_value(max(last3h))}", 20, render.TEXT),
            (age, 18, render.DIM),
        ])

    # ------------------------------------------------------------------
    # Urgent low: flash the key until the reading recovers
    # ------------------------------------------------------------------

    def _set_blinking(self, on: bool):
        if on and self._blink_key is None:
            self._blink_key = self.plugin.timer.set_interval(self._blink, BLINK_MS)
            self.show_alert()
        elif not on and self._blink_key is not None:
            self.plugin.timer.clear_interval(self._blink_key)
            self._blink_key = None
            self._blink_on = False

    def _blink(self):
        self._blink_on = not self._blink_on
        self._render()
