"""One LibreLinkUp session and polling loop shared by every glucose button."""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from librelinkup.client import AuthError, LibreLinkUpClient, RateLimitError, TermsError
from src.core import secrets
from src.core.env import load_env
from src.core.logger import Logger
from src.glucose.alerts import AlertManager
from src.glucose.history import History
from src.glucose.settings import GlucoseSettings

POLL_S = 60
# After the API rejects the credentials, stop hammering the login endpoint:
# LibreLinkUp locks the account for 5 min after 3 failures.
AUTH_RETRY_S = 30 * 60
# A reading older than this is shown dimmed and never triggers alerts
STALE_AFTER_S = 15 * 60
# Wait this long at start-up for StreamDock's global settings (stored credentials)
GLOBALS_WAIT_S = 3


@dataclass
class Snapshot:
    error: str | None = None           # short text for the button, None when ok
    value: float | None = None         # mg/dL
    trend: int = 4
    delta: float | None = None         # mg/dL per 5 min
    measured_at: datetime | None = None
    history: list = field(default_factory=list)
    alert: str | None = None
    patient_name: str = ""


class _Patient:
    def __init__(self):
        self.history = History()
        self.alerts  = AlertManager()
        self.snapshot: Snapshot | None = None


class GlucoseService:
    def __init__(self, plugin):
        self._plugin = plugin
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._globals_ready = threading.Event()

        self.settings = GlucoseSettings()
        self._global: dict = {}
        self._client: LibreLinkUpClient | None = None
        self._creds: tuple[str, str] | None = None
        self._creds_source = ""

        self._subscribers: list = []
        self._patients: dict[str | None, _Patient] = {}
        self._tasks: list = []

        self._retry_at = 0.0
        self._locked_until = 0.0
        self._auth_failed = False
        self._force = False

        load_env()
        self._apply_credentials()
        threading.Thread(target=self._run, daemon=True).start()

    # ------------------------------------------------------------------
    # Subscribers (buttons)
    # ------------------------------------------------------------------

    def subscribe(self, action) -> None:
        with self._lock:
            if action not in self._subscribers:
                self._subscribers.append(action)
            snap = self._patients.get(action.patient_id, _Patient()).snapshot
        if snap:
            action.on_snapshot(snap)
        self.refresh()

    def unsubscribe(self, action) -> None:
        with self._lock:
            if action in self._subscribers:
                self._subscribers.remove(action)

    def refresh(self, force: bool = False) -> None:
        if force:
            self._force = True
            if self._auth_failed:
                # Pick up a corrected .env without restarting StreamDock
                load_env(override=True)
                self._apply_credentials()
        self._wake.set()

    def run_task(self, fn) -> None:
        """Run fn(client) on the polling thread; the client is not thread-safe."""
        with self._lock:
            self._tasks.append(fn)
        self._wake.set()

    # ------------------------------------------------------------------
    # Settings and credentials
    # ------------------------------------------------------------------

    def on_global_settings(self, data: dict) -> None:
        self._global = dict(data or {})
        self.settings = GlucoseSettings.from_global(self._global)
        self._apply_credentials()
        self._globals_ready.set()
        self._rerender()

    def public_state(self) -> dict:
        """What the settings panel may see (never the password)."""
        email, _ = self._creds or ("", "")
        return {
            "email": email,
            "hasPassword": bool(self._creds),
            "source": self._creds_source,
            "settings": self.settings.__dict__,
            "status": self._status_text(),
        }

    def save_settings(self, values: dict) -> None:
        self._store_global({k: values[k] for k in GlucoseSettings().__dict__ if k in values})

    def save_credentials(self, email: str, password: str) -> None:
        update = {"email": email.strip()}
        if password:
            update["password_enc"] = secrets.protect(password)
        self._store_global(update)
        self.refresh(force=True)

    def _store_global(self, update: dict) -> None:
        merged = {**self._global, **update}
        self._plugin.set_global_settings(merged)
        self.on_global_settings(merged)

    def _apply_credentials(self) -> None:
        email, password, source = "", "", ""
        stored_email = self._global.get("email", "")
        stored_pw    = self._global.get("password_enc", "")
        if stored_email and stored_pw:
            try:
                email, password, source = stored_email, secrets.unprotect(stored_pw), "panel"
            except OSError:
                Logger.error("Stored password can't be decrypted (other Windows user?)")
        if not email:
            email    = os.environ.get("LLU_EMAIL", "")
            password = os.environ.get("LLU_PASSWORD", "")
            source   = ".env" if email and password else ""

        creds = (email, password) if email and password else None
        with self._lock:
            if creds == self._creds:
                return
            self._creds, self._creds_source = creds, source
            self._client = LibreLinkUpClient(*creds) if creds else None
            self._retry_at = self._locked_until = 0.0
            self._auth_failed = False
            # Readings and errors belonged to the previous account
            self._patients.clear()
        Logger.info(f"Credentials loaded from {source or 'nowhere'}")

    def _status_text(self) -> str:
        if not self._creds:
            return "Sin credenciales"
        if time.time() < self._locked_until:
            return "Cuenta bloqueada temporalmente por intentos fallidos"
        if self._auth_failed:
            return "LibreLinkUp rechazó el email o la contraseña"
        snaps = [p.snapshot for p in self._patients.values() if p.snapshot]
        if snaps and snaps[0].error:
            return f"Error: {snaps[0].error}"
        if snaps:
            return "Conectado"
        return "Conectando…"

    # ------------------------------------------------------------------
    # Polling thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        self._globals_ready.wait(GLOBALS_WAIT_S)
        next_poll = 0.0
        while True:
            self._wake.wait(timeout=max(0.0, next_poll - time.time()))
            self._wake.clear()

            with self._lock:
                tasks, self._tasks = self._tasks, []
                client = self._client
            for task in tasks:
                try:
                    task(client)
                except Exception as e:
                    Logger.error(f"Task failed: {e}")

            force, self._force = self._force, False
            if force or time.time() >= next_poll:
                self._poll_all(client, force)
                next_poll = time.time() + POLL_S

    def _poll_all(self, client: LibreLinkUpClient | None, force: bool) -> None:
        with self._lock:
            patient_ids = {a.patient_id for a in self._subscribers}
        for pid in patient_ids:
            snap = self._fetch(client, pid, force)
            if snap is None:
                continue  # backing off: keep showing the last snapshot
            with self._lock:
                self._patients.setdefault(pid, _Patient()).snapshot = snap
            self._publish(pid, snap)

    def _fetch(self, client: LibreLinkUpClient | None, pid: str | None, force: bool) -> Snapshot | None:
        if client is None:
            return Snapshot(error="Sin config")

        now = time.time()
        if now < self._locked_until or (now < self._retry_at and not force):
            return None

        try:
            reading = client.get_glucose_with_history(pid)
        except AuthError as e:
            Logger.error(f"LibreLinkUp: {e}. Fix the password and press the button.")
            self._auth_failed = True
            self._retry_at = now + AUTH_RETRY_S
            return Snapshot(error="Clave mala")
        except RateLimitError as e:
            Logger.error(f"LibreLinkUp: {e}; retrying in {e.retry_after}s")
            self._locked_until = now + e.retry_after + 5
            return Snapshot(error="Bloqueado")
        except TermsError as e:
            Logger.error(f"LibreLinkUp: {e}")
            self._retry_at = now + AUTH_RETRY_S
            return Snapshot(error="Acepta T&C")
        except Exception as e:
            Logger.error(f"LibreLinkUp fetch error: {e}")
            return Snapshot(error="Error API")

        self._auth_failed = False
        self._retry_at = 0.0
        if reading is None or reading.get("value") is None:
            return Snapshot(error="Sin datos")

        with self._lock:
            patient = self._patients.setdefault(pid, _Patient())
        patient.history.extend(reading["history"])
        at, value = reading["measured_at"], reading["value"]
        delta = patient.history.delta_5min(at, value) if at else None
        patient.history.add(at, value)

        alert = None
        if at and (datetime.now(timezone.utc) - at).total_seconds() <= STALE_AFTER_S:
            alert = patient.alerts.check(value, reading["trend"], self.settings, reading.get("patient_name", ""))
        Logger.info(f"Glucose updated: {value} mg/dL trend={reading['trend']}"
                    + (f" delta={delta:+.1f}" if delta is not None else "")
                    + (f" alert={alert}" if alert else ""))
        return Snapshot(
            value=value, trend=reading["trend"], delta=delta, measured_at=at,
            history=patient.history.points(),
            alert=alert, patient_name=reading.get("patient_name", ""),
        )

    def _publish(self, pid: str | None, snap: Snapshot) -> None:
        with self._lock:
            targets = [a for a in self._subscribers if a.patient_id == pid]
        for action in targets:
            try:
                action.on_snapshot(snap)
            except Exception as e:
                Logger.error(f"Render failed: {e}")

    def _rerender(self) -> None:
        """Settings changed (unit, thresholds): redraw without a new API call."""
        with self._lock:
            pairs = [(a, self._patients.get(a.patient_id)) for a in self._subscribers]
        for action, patient in pairs:
            if patient and patient.snapshot:
                action.on_snapshot(patient.snapshot)


_instance: GlucoseService | None = None
_instance_lock = threading.Lock()


def get_service(plugin) -> GlucoseService:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = GlucoseService(plugin)
            plugin.add_global_settings_listener(_instance.on_global_settings)
            plugin.get_global_settings()
        return _instance
