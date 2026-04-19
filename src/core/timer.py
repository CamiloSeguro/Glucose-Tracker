import threading
import time
import uuid


class Timer:
    def __init__(self):
        self._intervals: dict[str, dict] = {}
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            now = time.time()
            for key, entry in list(self._intervals.items()):
                if now - entry["last"] >= entry["delay"]:
                    try:
                        entry["callback"]()
                    except Exception:
                        pass
                    entry["last"] = now
            time.sleep(0.1)

    def set_interval(self, callback, delay_ms: int) -> str:
        key = str(uuid.uuid4())
        self._intervals[key] = {
            "callback": callback,
            "delay":    delay_ms / 1000.0,
            "last":     time.time(),
        }
        return key

    def clear_interval(self, key: str):
        self._intervals.pop(key, None)
