import argparse
import sys
import time
import threading

from src.core.env import load_env

# When frozen by PyInstaller, load .env from the same folder as the exe
load_env()

from src.core.plugin import Plugin
from src.core.timer import Timer
from src.core.logger import Logger


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-port",          required=True)
    parser.add_argument("-pluginUUID",    required=True)
    parser.add_argument("-registerEvent", required=True)
    parser.add_argument("-info",          required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        time.sleep(1)
        plugin = Plugin(
            port=int(args.port),
            plugin_uuid=args.pluginUUID,
            register_event=args.registerEvent,
            info=args.info,
        )
        plugin.timer = Timer()

        stop_event = threading.Event()
        plugin.set_on_close(stop_event.set)

        plugin.run()
        stop_event.wait()

    except Exception as e:
        Logger.error(f"Fatal error: {e}")
        sys.exit(0)


if __name__ == "__main__":
    main()
