"""Entry point: serve Tablekeeper on 0.0.0.0:$PORT (default 8080)."""
from __future__ import annotations

import os
import signal
import sys

from .api import Api
from .server import Server, make_handler
from .store import Store


def main() -> None:
    port = int(os.environ.get("PORT") or 8080)
    server = Server(("0.0.0.0", port), make_handler(Api(Store())))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # PID 1: stop promptly
    print(f"tablekeeper listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
