from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import mkdtemp
from threading import Thread
from typing import Any

from core import get_settings

FAKE_UNLEASH_PORT = 8181
WRITE_MCP_TEST_PORT = 8192

DONT_CARE_ADMIN_TOKEN = "*:*.dont-care-admin-token"
DONT_CARE_FRONTEND_TOKEN = "default:production.dont-care-frontend-token"
# The name the server is told the provider records Argus's own writes under, so
# a case can stage a change Argus made by recording one under it. Set rather
# than left to the default, so a developer's own `.env` cannot move it.
THE_ARGUS_ACTOR = "Argus"
# The environment every row a case stages is recorded in, set for the same reason.
THE_ENVIRONMENT = "production"

# The provider's own clock, which stands still: every answer is sent with it as
# its `Date`, which is what a flag's plan is dated by and what the history is
# then asked from. A case stages a change made since a plan by recording one
# after it.
THE_PROVIDER_S_TIME = datetime(2026, 8, 20, 11, 30, tzinfo=UTC)


class FakeUnleashHandler(BaseHTTPRequestHandler):
    """A flag provider in Unleash's own wire shape, with a memory.

    It answers the four surfaces the write tier uses - evaluation, the event
    log, the admin read of one feature, and the admin toggle - and a toggle
    actually changes what evaluation and the admin read then report. That is
    the point: `set_flag` returns only once evaluation agrees with the change,
    so a fake whose POST did not move its own state would hang rather than
    fail, and would prove nothing about the round trip.

    A toggle is not recorded in the event log. A case that needs a change in the
    history - Argus's or anybody's - stages it, at the time it says.
    """

    enabled_flags: set[str] = set()
    events: list[dict[str, Any]] = []

    def date_time_string(self, timestamp: float | None = None) -> str:
        """The `Date` every answer is sent with: the provider's own clock, which
        stands still at `THE_PROVIDER_S_TIME`, whatever this process's says."""
        return format_datetime(THE_PROVIDER_S_TIME, usegmt=True)

    def do_GET(self) -> None:
        feature = _the_feature_in(self.path)

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
        elif feature is not None:
            self._respond_with(self._the_feature(feature))
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

    def _the_feature(self, flag: str) -> dict[str, Any]:
        """One feature as the admin API answers for it - its `featureSchema`, in
        the one environment the server is told it serves."""
        return {
            "name": flag,
            "project": "default",
            "type": "release",
            "stale": False,
            "environments": [
                {"name": THE_ENVIRONMENT, "enabled": flag in self.enabled_flags,
                 "type": "production", "sortOrder": 1, "strategies": []}
            ]
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
def a_running_write_mcp() -> Generator[type[FakeUnleashHandler]]:
    """Runs a fake flag provider (stdlib http.server, background thread,
    answering evaluation, the event log, the admin read and admin toggles) plus
    a real `write_mcp_server` subprocess pointed at it - so a test can prove
    `write_mcp_client` reaches a real server without Docker or a real provider.
    The server holds one run, `THE_RUN_HELD`, in place of a database's
    (`a_write_server_holding_one_run`).

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
    # Somewhere of its own, so a suite never writes into the repository's
    # telemetry directory.
    env["TELEMETRY_DIRECTORY"] = mkdtemp(prefix="argus-telemetry-")
    env["UNLEASH_BASE_URL"] = f"http://127.0.0.1:{FAKE_UNLEASH_PORT}"
    env["UNLEASH_ADMIN_TOKEN"] = DONT_CARE_ADMIN_TOKEN
    env["UNLEASH_FRONTEND_TOKEN"] = DONT_CARE_FRONTEND_TOKEN
    env["UNLEASH_ACTOR"] = THE_ARGUS_ACTOR
    env["UNLEASH_ENVIRONMENT"] = THE_ENVIRONMENT
    env["WRITE_MCP_HOST"] = "127.0.0.1"
    env["WRITE_MCP_PORT"] = str(WRITE_MCP_TEST_PORT)
    # The suite is a package tree rather than an installed distribution, so a
    # subprocess told to run one of its modules is told where the tree is.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    write_mcp_process = subprocess.Popen(
        [sys.executable, "-m", "write_mcp_client_test.a_write_server_holding_one_run"], env=env
    )

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


def _the_feature_in(path: str) -> str | None:
    """The flag an admin read of one feature names, whose path's shape is
    `/api/admin/projects/{project}/features/{flag}` - or `None` for any other."""
    segments = path.partition("?")[0].strip("/").split("/")

    if len(segments) != 6 or segments[:2] != ["api", "admin"] or segments[4] != "features":
        return None

    return segments[5]


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
