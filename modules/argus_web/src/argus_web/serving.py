"""The process that serves `argus_web`: its telemetry, then the app.

A `main` of its own rather than `uvicorn argus_web.app:app`, because something
has to start this process's telemetry before the first request and close it
after the last, and the app's lifespan is the wrong place: every test that
drives the app through a `TestClient` runs the lifespan, and would install the
SDK for the whole test process and write a run directory each time it did.
"""

from __future__ import annotations

from argparse import ArgumentParser
from contextlib import closing
from typing import Final

import uvicorn
from argus_core import TelemetrySettings, get_settings
from argus_telemetry import start_telemetry

from argus_web.app import app

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-web"


def main(argv: list[str] | None = None) -> None:
    """The process: telemetry started, then serve until killed.

    `--host` and `--port` say where to listen, as they did when uvicorn's own
    command line was the entry point.
    """
    parser = ArgumentParser(description="Serves Argus's dashboard and its webhooks.")
    parser.add_argument("--host", default="127.0.0.1", help="the interface to listen on")
    parser.add_argument("--port", type=int, default=8000, help="the port to listen on")
    listening = parser.parse_args(argv)

    with closing(start_telemetry(TelemetrySettings.of(get_settings()), _SERVICE)):
        uvicorn.run(app, host=listening.host, port=listening.port)


if __name__ == "__main__":
    main()
