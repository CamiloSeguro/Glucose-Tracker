import base64
import subprocess
import threading
import time

from src.core.logger import Logger
from src.glucose.settings import GlucoseSettings

FALLING_FAST = 7

# Minimum seconds between two notifications of the same kind
REPEAT_S = {
    "urgent_low":   5 * 60,
    "low":          15 * 60,
    "falling_fast": 15 * 60,
    "very_high":    60 * 60,
}


def classify(value: float, trend: int, s: GlucoseSettings) -> str | None:
    if value < s.urgent_low:
        return "urgent_low"
    if value < s.low:
        return "low"
    if trend == FALLING_FAST and value < s.high:
        return "falling_fast"
    if value > s.very_high:
        return "very_high"
    return None


class AlertManager:
    """Decides when to notify; one instance per followed person."""

    def __init__(self, notify=None):
        self._notify = notify or show_toast
        self._last_sent: dict[str, float] = {}

    def check(self, value: float | None, trend: int, s: GlucoseSettings, name: str = "") -> str | None:
        """Returns the alert kind (for the button to react) and sends a toast if due."""
        if value is None or not s.alerts:
            return None
        kind = classify(value, trend, s)
        if kind is None:
            # Back in a safe state: the next episode alerts immediately
            self._last_sent.clear()
            return None

        now = time.time()
        if now - self._last_sent.get(kind, 0) >= REPEAT_S[kind]:
            self._last_sent[kind] = now
            title, body = _message(kind, s.format_value(value), s.unit_label, name)
            self._notify(title, body, kind == "urgent_low")
        return kind


def _message(kind: str, value: str, unit: str, name: str) -> tuple[str, str]:
    who = f"{name}: " if name else ""
    return {
        "urgent_low":   ("Glucosa MUY BAJA", f"{who}{value} {unit}. Actúa ahora."),
        "low":          ("Glucosa baja",     f"{who}{value} {unit}"),
        "falling_fast": ("Bajando rápido",   f"{who}{value} {unit} y cayendo rápido"),
        "very_high":    ("Glucosa muy alta", f"{who}{value} {unit}"),
    }[kind]


_TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
<toast{scenario}><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual>
<audio src="{sound}" /><actions><action content="OK" arguments="ok" activationType="system" /></actions></toast>
'@)
$appId = '{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))


def show_toast(title: str, body: str, urgent: bool = False) -> None:
    """Windows toast via PowerShell (no extra dependency). Fire and forget.

    Urgent toasts stay on screen with a looping alarm until dismissed.
    """
    script = _TOAST_PS.format(
        title=_xml_escape(title), body=_xml_escape(body),
        scenario=' scenario="alarm"' if urgent else "",
        sound="ms-winsoundevent:Notification.Looping.Alarm2" if urgent else "ms-winsoundevent:Notification.Reminder",
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    def run():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=30,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            Logger.error(f"Toast failed: {e}")

    threading.Thread(target=run, daemon=True).start()
    Logger.info(f"Alert: {title} - {body}")
