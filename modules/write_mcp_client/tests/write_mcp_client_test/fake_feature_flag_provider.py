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
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from argus_testkit import a_free_port
from core import get_settings
from mcp.server.streamable_http import CONTENT_TYPE_JSON, CONTENT_TYPE_SSE
from mcp.types import (
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
    JSONRPCRequest,
    JSONRPCResponse,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION

# Where the fakes listen: loopback, on whatever port the operating system hands
# out. A port written here is shared by every copy of this suite running at
# once - a second checkout's, or a WSL run's, whose listeners `wslrelay.exe`
# forwards to this machine's loopback - and one copy's client then talks to the
# other's server.
LOOPBACK = "127.0.0.1"
ANY_FREE_PORT = 0
# How long a started server has to answer before it is taken to hang. A guard
# against a hang and nothing tighter: a server that fails to start is seen
# exiting and said at once, and with every suite running at once a start that
# takes three seconds idle has been measured at over fifteen.
LONG_PAST_ANY_START_SECONDS = 180.0
A_MOMENT_BETWEEN_KNOCKS_SECONDS = 0.2
# How long one knock on a starting server waits for its answer.
A_KNOCK_SECONDS = 1.0

# Who the write tier says it is when a session is opened over MCP: the name its
# server is built with. What a knock is answered with before the server counts
# as up - any other answer on the port is somebody else's.
THE_WRITE_TIER = "argus-write-mcp"
# Where it serves MCP, and the parts of the protocol a knock speaks: JSON-RPC's
# version, the one request's id, who is knocking, and the field of a
# server-sent event that carries the answer. The knock opens a session as the
# client does, at the newest version the SDK opens one with by handshake
# (`LATEST_HANDSHAKE_VERSION`, from the SDK's own types package): its newest
# version of all is one spoken without a handshake.
MCP_PATH: Final = "/mcp"
JSONRPC_VERSION: Final = "2.0"
A_KNOCK_ID = 1
THE_KNOCKER = Implementation(name="write-mcp-client-suite", version="0")
SSE_DATA_FIELD: Final = "data:"

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
        elif self.path.startswith("/api/admin/search/events"):
            self._respond_with(self._a_page_of_the_events())
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

    def _a_page_of_the_events(self) -> dict[str, Any]:
        """One page of the event search, as Unleash answers it: newest first
        (`created_at`, then `id`, descending), from `offset` for `limit` rows,
        with how many there are in all. Every staged row is a toggle in
        `THE_ENVIRONMENT`, so the search's filters leave all of them."""
        asked = parse_qs(urlsplit(self.path).query)
        offset = int(asked.get("offset", ["0"])[0])
        limit = int(asked.get("limit", ["50"])[0])
        newest_first = sorted(self.events,
                              key=lambda event: (event["createdAt"], event["id"]),
                              reverse=True)

        return {"events": newest_first[offset:offset + limit], "total": len(self.events)}

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

    The fake binds whatever port it is given and is asked which; the server
    is handed one the operating system just said was free, and counts as up
    only once it answers as the write tier on it.
    """
    fake_unleash = HTTPServer((LOOPBACK, ANY_FREE_PORT), FakeUnleashHandler)
    server_thread = Thread(target=fake_unleash.serve_forever, daemon=True)
    server_thread.start()

    write_mcp_port = a_free_port()
    env = os.environ.copy()
    # Somewhere of its own, so a suite never writes into the repository's
    # telemetry directory.
    telemetry = TemporaryDirectory(prefix="argus-telemetry-", ignore_cleanup_errors=True)
    env["TELEMETRY_DIRECTORY"] = telemetry.name
    env["UNLEASH_BASE_URL"] = f"http://{LOOPBACK}:{fake_unleash.server_address[1]}"
    env["UNLEASH_ADMIN_TOKEN"] = DONT_CARE_ADMIN_TOKEN
    env["UNLEASH_FRONTEND_TOKEN"] = DONT_CARE_FRONTEND_TOKEN
    env["UNLEASH_ACTOR"] = THE_ARGUS_ACTOR
    env["UNLEASH_ENVIRONMENT"] = THE_ENVIRONMENT
    env["WRITE_MCP_HOST"] = LOOPBACK
    env["WRITE_MCP_PORT"] = str(write_mcp_port)
    # The suite is a package tree rather than an installed distribution, so a
    # subprocess told to run one of its modules is told where the tree is.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    write_mcp_process = subprocess.Popen(
        [sys.executable, "-m", "write_mcp_client_test.a_write_server_holding_one_run"], env=env
    )

    # Put back whole on the way out, so a variable that was set before keeps
    # its value rather than being deleted with the ones set here.
    the_environment_before = dict(os.environ)
    os.environ["WRITE_MCP_HOST"] = env["WRITE_MCP_HOST"]
    os.environ["WRITE_MCP_PORT"] = env["WRITE_MCP_PORT"]
    get_settings.cache_clear()

    try:
        _wait_for_write_mcp(write_mcp_process, f"http://{LOOPBACK}:{write_mcp_port}{MCP_PATH}")
        yield FakeUnleashHandler
    finally:
        write_mcp_process.terminate()
        write_mcp_process.wait(timeout=10)
        telemetry.cleanup()
        fake_unleash.shutdown()
        fake_unleash.server_close()
        server_thread.join()
        FakeUnleashHandler.enabled_flags = set()
        FakeUnleashHandler.events = []
        os.environ.clear()
        os.environ.update(the_environment_before)
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


def _wait_for_write_mcp(process: subprocess.Popen[bytes], url: str) -> None:
    """Waits until the server at `url` answers as the write tier, and says at
    once that it never will where its process has ended.

    As the write tier rather than at all: any other answer on the port says
    only that something is listening there - another copy of this suite's
    server, or one a killed run left behind - while this one may have failed to
    take the port, and will then be seen ending."""
    deadline = time.monotonic() + LONG_PAST_ANY_START_SECONDS
    while time.monotonic() < deadline:
        ended_with = process.poll()
        if ended_with is not None:
            raise RuntimeError(
                f"write_mcp test server ended with [{ended_with}] before it answered"
            )
        try:
            if _who_answers_at(url) == THE_WRITE_TIER:
                return
        except (urllib.error.HTTPError, ValueError):
            # Something that is no MCP server answered - refusing the knock,
            # or with something that is not an answer to it.
            pass
        except OSError:
            # Not answering yet: refused, or taken and not answered within the
            # knock's second - which `urlopen` raises bare, not as a `URLError`.
            pass
        time.sleep(A_MOMENT_BETWEEN_KNOCKS_SECONDS)
    raise TimeoutError(
        f"write_mcp test server did not answer within {LONG_PAST_ANY_START_SECONDS:.0f}s"
    )


def _who_answers_at(url: str) -> str:
    """The name the MCP server at `url` gives when a session is opened with it
    (`initialize`), answered as a server-sent event or as JSON - whichever the
    server chooses."""
    knock = InitializeRequest(params=InitializeRequestParams(
        protocol_version=LATEST_HANDSHAKE_VERSION,
        capabilities=ClientCapabilities(),
        client_info=THE_KNOCKER
    ))
    asked = JSONRPCRequest(jsonrpc=JSONRPC_VERSION, id=A_KNOCK_ID,
                           **knock.model_dump(by_alias=True, mode="json", exclude_none=True))
    request = urllib.request.Request(
        url,
        data=asked.model_dump_json(by_alias=True, exclude_none=True).encode(),
        headers={"Content-Type": CONTENT_TYPE_JSON,
                 "Accept": f"{CONTENT_TYPE_JSON}, {CONTENT_TYPE_SSE}"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=A_KNOCK_SECONDS) as answered:
        said = answered.read().decode()
        as_an_event = answered.headers.get_content_type() == CONTENT_TYPE_SSE

    if as_an_event:
        said = next((line.removeprefix(SSE_DATA_FIELD) for line in said.splitlines()
                     if line.startswith(SSE_DATA_FIELD)), "")

    response = JSONRPCResponse.model_validate_json(said)

    return InitializeResult.model_validate(response.result).server_info.name
