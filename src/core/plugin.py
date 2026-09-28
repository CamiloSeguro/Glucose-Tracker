import json
import re
import websocket

from src.core.action_factory import ActionFactory
from src.core.logger import Logger


class Plugin:
    def __init__(self, port: int, plugin_uuid: str, register_event: str, info: str):
        self.port = port
        self.plugin_uuid = plugin_uuid
        self.register_event = register_event
        self.info = info
        self.ws: websocket.WebSocketApp | None = None
        self._actions: dict[str, object] = {}
        self._factory = ActionFactory()
        self._on_close_cb = None
        self._global_listeners = []

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def run(self):
        self.ws = websocket.WebSocketApp(
            f"ws://127.0.0.1:{self.port}",
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever()

    def stop(self):
        if self.ws:
            self.ws.close()

    def set_on_close(self, callback):
        self._on_close_cb = callback

    # ------------------------------------------------------------------
    # Global settings helpers
    # ------------------------------------------------------------------

    def set_global_settings(self, payload: dict):
        if self.ws:
            self.ws.send(json.dumps({
                "event":   "setGlobalSettings",
                "context": self.plugin_uuid,
                "payload": payload,
            }))

    def add_global_settings_listener(self, callback):
        self._global_listeners.append(callback)

    def get_global_settings(self):
        if self.ws:
            self.ws.send(json.dumps({
                "event":   "getGlobalSettings",
                "context": self.plugin_uuid,
            }))

    # ------------------------------------------------------------------
    # Action lookup
    # ------------------------------------------------------------------

    def get_action(self, context: str):
        return self._actions.get(context)

    def get_actions(self, action_type: str | None = None) -> list:
        if action_type is None:
            return list(self._actions.values())
        return [a for a in self._actions.values() if a.action == action_type]

    # ------------------------------------------------------------------
    # WebSocket handlers
    # ------------------------------------------------------------------

    def _on_open(self, ws):
        ws.send(json.dumps({"event": self.register_event, "uuid": self.plugin_uuid}))
        Logger.info("Connected to StreamDock")

    def _on_message(self, ws, message: str):
        try:
            data = json.loads(message)
        except Exception:
            return

        event   = data.get("event", "")
        context = data.get("context", "")
        action  = data.get("action", "")
        payload = data.get("payload", {})

        if event == "willAppear":
            settings = payload.get("settings", {})
            inst = self._factory.create_action(action, context, settings, self)
            if inst:
                self._actions[context] = inst
                if hasattr(inst, "will_appear"):
                    inst.will_appear(settings)

        elif event == "willDisappear":
            inst = self._actions.pop(context, None)
            if inst and hasattr(inst, "will_disappear"):
                inst.will_disappear()

        elif event in ("keyDown", "keyUp", "dialDown", "dialUp", "dialRotate"):
            inst = self._actions.get(context)
            if inst:
                method = self._camel_to_snake(event)
                if hasattr(inst, method):
                    getattr(inst, method)(payload)

        elif event == "didReceiveSettings":
            inst = self._actions.get(context)
            if inst:
                inst.settings = payload.get("settings", {})
                if hasattr(inst, "did_receive_settings"):
                    inst.did_receive_settings(inst.settings)

        elif event == "didReceiveGlobalSettings":
            settings = payload.get("settings", {})
            for callback in self._global_listeners:
                callback(settings)
            for inst in self._actions.values():
                if hasattr(inst, "did_receive_global_settings"):
                    inst.did_receive_global_settings(settings)

        elif event in ("propertyInspectorDidAppear", "propertyInspectorDidDisappear"):
            inst = self._actions.get(context)
            method = self._camel_to_snake(event)
            if inst and hasattr(inst, method):
                getattr(inst, method)(payload)

        elif event == "sendToPlugin":
            inst = self._actions.get(context)
            if inst and hasattr(inst, "send_to_plugin"):
                inst.send_to_plugin(payload)

        elif event in ("deviceDidConnect", "deviceDidDisconnect",
                       "applicationDidLaunch", "applicationDidTerminate",
                       "systemDidWakeUp"):
            method = self._camel_to_snake(event)
            for inst in self._actions.values():
                if hasattr(inst, method):
                    getattr(inst, method)(data)

    def _on_error(self, ws, error):
        Logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, code, msg):
        Logger.info(f"WebSocket closed (code={code})")
        if self._on_close_cb:
            self._on_close_cb()

    @staticmethod
    def _camel_to_snake(name: str) -> str:
        s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()
