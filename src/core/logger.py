import logging
import os
import sys


class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_logger()
        return cls._instance

    def _init_logger(self):
        self._logger = logging.getLogger("StreamDockPlugin")
        self._logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        self._logger.addHandler(console)

        try:
            if getattr(sys, "frozen", False):
                log_dir = os.path.join(os.path.dirname(sys.executable), "logs")
            else:
                log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, "plugin.log"), encoding="utf-8")
            fh.setFormatter(fmt)
            self._logger.addHandler(fh)
        except Exception:
            pass

    @classmethod
    def get_logger(cls) -> logging.Logger:
        return cls()._logger

    @classmethod
    def info(cls, msg): cls.get_logger().info(msg)

    @classmethod
    def error(cls, msg): cls.get_logger().error(msg)

    @classmethod
    def warning(cls, msg): cls.get_logger().warning(msg)

    @classmethod
    def debug(cls, msg): cls.get_logger().debug(msg)
