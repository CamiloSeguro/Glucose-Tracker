import importlib
import inspect
import os
import sys

from src.core.action import Action
from src.core.logger import Logger

# Explicit imports so PyInstaller bundles them and they are always available
from src.actions.glucose_action import GlucoseAction

_BUILTIN_ACTIONS = [GlucoseAction]


class ActionFactory:
    def __init__(self):
        self._registry: dict[str, type] = {}
        self._register_builtins()
        self._scan_actions()

    def _register_builtins(self):
        for cls in _BUILTIN_ACTIONS:
            key = cls.__name__.lower().replace("action", "")
            self._registry[key] = cls
            Logger.debug(f"Registered builtin action: {key} → {cls.__name__}")

    def _scan_actions(self):
        if getattr(sys, "frozen", False):
            return  # directory scan not available in frozen mode

        actions_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "actions"))
        if not os.path.isdir(actions_dir):
            return

        for fname in os.listdir(actions_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            module_name = f"src.actions.{fname[:-3]}"
            try:
                module = importlib.import_module(module_name)
                for _, cls in inspect.getmembers(module, inspect.isclass):
                    if issubclass(cls, Action) and cls is not Action:
                        key = cls.__name__.lower().replace("action", "")
                        if key not in self._registry:
                            self._registry[key] = cls
                            Logger.debug(f"Registered scanned action: {key} → {cls.__name__}")
            except Exception as e:
                Logger.error(f"Failed to load {module_name}: {e}")

    def create_action(self, action_uuid: str, context: str, settings: dict, plugin) -> Action | None:
        # UUID format: com.cgm.freestyle.glucose → key = "glucose"
        key = action_uuid.split(".")[-1].lower()
        cls = self._registry.get(key)
        if cls is None:
            Logger.warning(f"No action registered for key '{key}' (uuid={action_uuid})")
            return None
        try:
            return cls(action_uuid, context, settings, plugin)
        except Exception as e:
            Logger.error(f"Failed to instantiate {cls.__name__}: {e}")
            return None
