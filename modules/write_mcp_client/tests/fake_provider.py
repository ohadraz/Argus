from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

from argus_core.config import get_settings

FAKE_UNLEASH_PORT = 8181
WRITE_MCP_TEST_PORT = 8192

DONT_CARE_ADMIN_TOKEN = "*:*.dont-care-admin-token"
DONT_CARE_FRONTEND_TOKEN = "default:production.dont-care-frontend-token"


class FakeUnleashHandler(BaseHTTPRequestHandler):
    """A flag provider in Unleash's own wire shape, with a memory.

    It answers the three surfaces the write tier uses - evaluation, the event
    log, and the admin toggle - and a toggle actually changes what evaluation
    then reports. That is the point: `set_flag` returns only once evaluation
    agrees with the change, so a fake whose POST did not move its own state
    would hang rather than fail, and would prove nothing about the round trip.
    """

    enabled_flags: set[str] = set()
    events: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/api/frontend"):
            self._respond_with(
                {
                    "toggles": [
                        {"name": flag, "enabled": True}
                        for flag in sorted(self.enabled_flags)
                    ]
                }
            )
        elif self.path.startswith("/api/admin/events"):
            self._respond_with(
                {"version": 1, "events": self.events, "totalEvents": len(self.events)}
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        flag, state = _flag_and_state_in(self.path)

        if flag is None:
            self.send_response(404)
            self.end_headers()
            return

        if state == "on":
            type(self).enabled_flags = self.enabled_flags | {flag}
        else:
            type(self).enabled_flags = self.enabled_flags - {flag}

        self._respond_with({})

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
def a_running_write_mcp() -> Iterator[type[FakeUnleashHandler]]:
    """Runs a fake flag provider (stdlib http.server, background thread,
    answering evaluation, the event log and admin toggles) plus a real
    `write_mcp_server` subprocess pointed at it - so a test can prove
    `write_mcp_client` reaches a real server without Docker or a real provider.

    Yields the handler class, so a test can set `.enabled_flags` and `.events`
    before calling through the client, and read `.enabled_flags` back
    afterwards to see whether the world actually changed.

    A context manager rather than a `conftest.py` fixture: mypy identifies a
    module by its filename, so a second `conftest` anywhere under `modules/`
    collides with the first and aborts the whole type-check run. This file's
    name is its own, and the test wraps it in a one-line fixture.
    """
    fake_unleash = HTTPServer(("127.0.0.1", FAKE_UNLEASH_PORT), FakeUnleashHandler)
    server_thread = Thread(target=fake_unleash.serve_forever, daemon=True)
    server_thread.start()

    env = os.environ.copy()
    env["UNLEASH_BASE_URL"] = f"http://127.0.0.1:{FAKE_UNLEASH_PORT}"
    env["UNLEASH_ADMIN_TOKEN"] = DONT_CARE_ADMIN_TOKEN
    env["UNLEASH_FRONTEND_TOKEN"] = DONT_CARE_FRONTEND_TOKEN
    env["WRITE_MCP_HOST"] = "127.0.0.1"
    env["WRITE_MCP_PORT"] = str(WRITE_MCP_TEST_PORT)
    write_mcp_process = subprocess.Popen([sys.executable, "-m", "write_mcp_server.server"], env=env)

    os.environ["WRITE_MCP_HOST"] = env["WRITE_MCP_HOST"]
    os.environ["WRITE_MCP_PORT"] = env["WRITE_MCP_PORT"]
    get_settings.cache_clear()

    try:
        _wait_for_write_mcp()
        yield FakeUnleashHandler
    finally:
        write_mcp_process.terminate()
        write_mcp_process.wait(timeout=10)
        fake_unleash.shutdown()
        fake_unleash.server_close()
        server_thread.join()
        FakeUnleashHandler.enabled_flags = set()
        FakeUnleashHandler.events = []
        del os.environ["WRITE_MCP_HOST"]
        del os.environ["WRITE_MCP_PORT"]
        get_settings.cache_clear()


def _flag_and_state_in(path: str) -> tuple[str | None, str]:
    """Reads the flag and the state off an admin toggle path, whose shape is
    `/api/admin/projects/{project}/features/{flag}/environments/{env}/{on|off}`.
    """
    segments = path.strip("/").split("/")

    if len(segments) != 9 or segments[-1] not in ("on", "off"):
        return None, ""

    return segments[5], segments[-1]


def _wait_for_write_mcp(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{WRITE_MCP_TEST_PORT}/mcp", timeout=1.0)
            return
        except urllib.error.HTTPError:
            return  # a real HTTP response (even an error one) means the server is up
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise TimeoutError("write_mcp test server did not become ready within the timeout")
