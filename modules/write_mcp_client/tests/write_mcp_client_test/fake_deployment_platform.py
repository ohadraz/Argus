from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

from argus_core import get_settings

FAKE_PLATFORM_PORT = 8184

RESTART_ACTION_PATH = "/argocd/{application}/resource/actions/v2"
APPLICATION_PATH = "/argocd/{application}"
ROLLBACK_PATH = "/argocd/{application}/rollback"
SPEC_PATH = "/argocd/{application}/spec"

# What the gauge reads before anything is restarted, and how far a restart
# moves it. Both arbitrary: what a caller can tell from this reading is that it
# *changed*, and nothing else - the two clocks involved are not the same clock.
THE_PROCESS_THAT_WAS_SERVING = 1_756_000_000.0
A_NEW_PROCESS_LATER = 600.0

# Two entries, because a rollback is addressed to a history entry and an
# application with one entry has nothing to return to. The revisions are commit
# shapes rather than real commits: what a caller can tell from them is which
# entry it came *from*, which is what the descriptor records.
THE_REVISION_RUNNING_NOW = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
THE_HISTORY_RUNNING_NOW = 2
THE_HISTORY_BEFORE_IT = 1

_APPLICATION_IN = re.compile(r"^/argocd/(?P<application>[^/]+)")


class FakeDeploymentPlatformHandler(BaseHTTPRequestHandler):
    """A deployment platform in Argo CD's own wire shape, with a memory.

    It answers the surfaces a restart needs - the resource action, and the gauge
    that says which process is serving - and running the action actually moves
    the gauge. That is the point: `restart_service` returns only once the start
    time has changed, so a fake whose POST did not move its own state would hang
    rather than fail, and would prove nothing about the round trip.

    It answers the surfaces a rollback needs for the same reason, and the same
    way. A rollback is three requests against three routes - the application is
    read for which entry is running and whether the platform reconciles it
    itself, reconciliation is suspended, and only then is the rollback asked for
    - so a fake that served a static application would let a caller that never
    suspended anything pass. Here the spec route actually writes the policy, and
    the rollback route refuses while the policy says the platform syncs itself,
    exactly as a real server refuses it.

    One server for every role, because one deployment's Argo CD and its metrics
    endpoint are two addresses and the test only needs them to be reachable -
    which settings point where is what the context manager below decides.
    """

    process_start_time_seconds: float = THE_PROCESS_THAT_WAS_SERVING
    actions_run: list[dict[str, Any]] = []
    syncs_itself: bool = True
    rolled_back_to: list[int] = []
    sync_policies_written: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        if self.path.startswith("/metrics"):
            self._respond_with([self._the_minute_in_progress()])
        elif self._names_an_application() and self.path.count("/") == 2:
            self._respond_with(self._the_application())
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self) -> None:
        if not self.path.endswith("/spec"):
            self.send_response(404)
            self.end_headers()
            return

        policy = self._the_body().get("syncPolicy", {})
        type(self).sync_policies_written = self.sync_policies_written + [policy]
        # The write is real, because the refusal below reads it back. A fake
        # that accepted the policy and kept syncing would let a rollback pass
        # that had suspended nothing.
        type(self).syncs_itself = policy.get("automated") is not None

        self._respond_with({})

    def do_POST(self) -> None:
        if self.path.endswith("/rollback"):
            self._roll_back()
            return

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

    def _roll_back(self) -> None:
        """Refused while the application syncs itself, as the platform refuses it.

        The refusal is what makes the order of a rollback's three requests
        observable. A fake that always accepted would answer the same whether
        the caller suspended reconciliation first or not, and the one thing this
        route exists to witness is that it did.
        """
        if self.syncs_itself:
            self.send_response(400)
            self.end_headers()
            return

        type(self).rolled_back_to = self.rolled_back_to + [self._the_body()["id"]]

        self._respond_with({})

    def _names_an_application(self) -> bool:
        return _APPLICATION_IN.match(self.path) is not None

    def _the_application(self) -> dict[str, Any]:
        """The application in Argo CD's own shape, as much of it as is read.

        `automated` is present or absent rather than true or false, because that
        is how Argo CD spells it and how the caller reads it - a fake reporting
        `{"automated": false}` would be read as syncing itself and would make a
        correct caller look broken.
        """
        policy: dict[str, Any] = {"automated": {}} if self.syncs_itself else {}

        return {
            "spec": {"syncPolicy": policy},
            "status": {
                "history": [
                    {
                        "id": THE_HISTORY_BEFORE_IT,
                        "revision": THE_REVISION_BEFORE_IT
                    },
                    {
                        "id": THE_HISTORY_RUNNING_NOW,
                        "revision": THE_REVISION_RUNNING_NOW
                    }
                ]
            }
        }

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
    """Runs a fake deployment platform and points the platform settings at it.

    Entered *around* `a_running_write_mcp` rather than inside it: that manager
    copies the environment to launch the server subprocess, so the settings set
    here are the ones the subprocess resolves from. Nesting is what orders the
    two, and the write server must start second.

    Yields the handler class, so a test can read back what the platform was
    asked to do, which process it now reports serving, which history entry it
    was rolled back to, and whether it is still reconciling itself.

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
    os.environ["ARGOCD_APPLICATION_PATH"] = APPLICATION_PATH
    os.environ["ARGOCD_ROLLBACK_PATH"] = ROLLBACK_PATH
    os.environ["ARGOCD_SPEC_PATH"] = SPEC_PATH
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
        FakeDeploymentPlatformHandler.syncs_itself = True
        FakeDeploymentPlatformHandler.rolled_back_to = []
        FakeDeploymentPlatformHandler.sync_policies_written = []
        del os.environ["ARGOCD_BASE_URL"]
        del os.environ["ARGOCD_RESTART_ACTION_PATH"]
        del os.environ["ARGOCD_APPLICATION_PATH"]
        del os.environ["ARGOCD_ROLLBACK_PATH"]
        del os.environ["ARGOCD_SPEC_PATH"]
        del os.environ["ARGOCD_AUTH_TOKEN"]
        del os.environ["TARGET_SERVICE_URL"]
        get_settings.cache_clear()
