from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

from argus_core import get_settings

FAKE_PLATFORM_PORT = 8184

RESTART_ACTION_PATH = "/argocd/{application}/resource/actions/v2"

# What the gauge reads before anything is restarted, and how far a restart
# moves it. Both arbitrary: what a caller can tell from this reading is that it
# *changed*, and nothing else - the two clocks involved are not the same clock.
THE_PROCESS_THAT_WAS_SERVING = 1_756_000_000.0
A_NEW_PROCESS_LATER = 600.0


class FakeDeploymentPlatformHandler(BaseHTTPRequestHandler):
    """A deployment platform in Argo CD's own wire shape, with a memory.

    It answers the two surfaces a restart needs - the resource action, and the
    gauge that says which process is serving - and running the action actually
    moves the gauge. That is the point: `restart_service` returns only once the
    start time has changed, so a fake whose POST did not move its own state
    would hang rather than fail, and would prove nothing about the round trip.

    One server for both roles, because one deployment's Argo CD and its metrics
    endpoint are two addresses and the test only needs them to be reachable -
    which settings point where is what the context manager below decides.
    """

    process_start_time_seconds: float = THE_PROCESS_THAT_WAS_SERVING
    actions_run: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/metrics"):
            self._respond_with([self._the_minute_in_progress()])
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if "/resource/actions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return

        type(self).actions_run = self.actions_run + [
            {"path": self.path, "asked_for": self._the_body()}
        ]
        # A restart is a new process, and the gauge moving is the only way
        # anything outside can tell that it happened.
        type(self).process_start_time_seconds = (
            self.process_start_time_seconds + A_NEW_PROCESS_LATER
        )

        self._respond_with({})

    def _the_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))

        if not length:
            return {}

        body: dict[str, Any] = json.loads(self.rfile.read(length))

        return body

    def _the_minute_in_progress(self) -> dict[str, Any]:
        """One bucket, in the shape the metrics channel serves them.

        Only the start time is read here, but a window that carried nothing
        else would be a window no real service produces - and the reader takes
        the *latest* minute, which a one-minute window makes unambiguous.
        """
        return {
            "bucket_id": "2026-08-20T11:00:00Z",
            "error_rate": 0.01,
            "p50_ms": 80,
            "p95_ms": 200,
            "request_volume": 1000,
            "memory_used_bytes": 440 * 1024**2,
            "memory_limit_bytes": None,
            "process_start_time_seconds": self.process_start_time_seconds,
        }

    def _respond_with(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging


@contextmanager
def a_running_platform() -> Iterator[type[FakeDeploymentPlatformHandler]]:
    """Runs a fake deployment platform and points the restart settings at it.

    Entered *around* `a_running_write_mcp` rather than inside it: that manager
    copies the environment to launch the server subprocess, so the settings set
    here are the ones the subprocess resolves from. Nesting is what orders the
    two, and the write server must start second.

    Yields the handler class, so a test can read back what the platform was
    asked to do and which process it now reports serving.

    A context manager rather than a `conftest.py` fixture, for the reason the
    flag provider's is one: mypy identifies a module by its filename, so a
    second `conftest` anywhere under `modules/` collides with the first.
    """
    platform = HTTPServer(("127.0.0.1", FAKE_PLATFORM_PORT), FakeDeploymentPlatformHandler)
    platform_thread = Thread(target=platform.serve_forever, daemon=True)
    platform_thread.start()

    address = f"http://127.0.0.1:{FAKE_PLATFORM_PORT}"
    os.environ["ARGOCD_BASE_URL"] = address
    os.environ["ARGOCD_RESTART_ACTION_PATH"] = RESTART_ACTION_PATH
    # Empty on purpose: the stand-in takes no credential, and an inherited one
    # would be sent as a header a real server would then refuse.
    os.environ["ARGOCD_AUTH_TOKEN"] = ""
    os.environ["TARGET_SERVICE_URL"] = address
    get_settings.cache_clear()

    try:
        yield FakeDeploymentPlatformHandler
    finally:
        platform.shutdown()
        platform.server_close()
        platform_thread.join()
        FakeDeploymentPlatformHandler.process_start_time_seconds = THE_PROCESS_THAT_WAS_SERVING
        FakeDeploymentPlatformHandler.actions_run = []
        del os.environ["ARGOCD_BASE_URL"]
        del os.environ["ARGOCD_RESTART_ACTION_PATH"]
        del os.environ["ARGOCD_AUTH_TOKEN"]
        del os.environ["TARGET_SERVICE_URL"]
        get_settings.cache_clear()
