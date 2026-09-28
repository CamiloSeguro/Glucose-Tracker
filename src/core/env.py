import os
import sys

from dotenv import load_dotenv


def env_path() -> str:
    """.env lives next to main.exe when frozen, next to main.py in development."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, ".env")


def load_env(override: bool = False) -> None:
    load_dotenv(env_path(), override=override)
