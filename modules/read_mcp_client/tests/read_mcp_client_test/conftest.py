from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest
from argus_core import get_settings, parse_iso
from metrics_source.prometheus_adapter import QUERIES

FAKE_TARGET_SERVICE_PORT = 8180
READ_MCP_TEST_PORT = 8190

# Where the fake answers as Prometheus: under a prefix, the way the Target
# Environment's own stand-in does, so the setting carries a path and the
# adapter's own path is appended to it.
PROMETHEUS_PREFIX = "/prometheus"
THE_RANGE_QUERY_PATH = f"{PROMETHEUS_PREFIX}/api/v1/query_range"

# Which bucket field each query asks for - the inverse of what the adapter asks.
FIELD_ASKED_BY = {query: field for field, query in QUERIES.items()}


class FakeTargetServiceHandler(BaseHTTPRequestHandler):
    logs: list[str] = []
    # One row per minute, in the bucket's own field names. Served as Prometheus
    # would serve them - one series per query, a sample at the end of the minute
    # it describes - because the adapter under test is the one that would read
    # a real Prometheus.
    metrics: list[dict[str, object]] = []
    # One Argo CD `status.history` entry per deploy the scenario had. Served
    # under `/argocd/<application>`, in Argo CD's own wire shape, because the
    # adapter under test is the one that would read a real server.
    deploys: list[dict[str, object]] = []

    def do_GET(self) -> None:
        url = urlsplit(self.path)

        if url.path == "/logs":
            self._respond_with(self.logs)
        elif url.path == THE_RANGE_QUERY_PATH:
            self._respond_with(self._a_matrix(parse_qs(url.query)))
        elif url.path.startswith("/argocd/"):
            application = url.path.removeprefix("/argocd/")
            self._respond_with(
                {
                    "metadata": {"name": application, "namespace": "argocd"},
                    "status": {"history": self.deploys},
                }
            )
        else:
            self.send_response(404)
            self.end_headers()

    def _a_matrix(self, params: dict[str, list[str]]) -> dict[str, object]:
        """The rows' readings for one query, in Prometheus's matrix envelope,
        from the minutes whose ends fall between `start` and `end`."""
        field = FIELD_ASKED_BY[params["query"][0]]
        start, end = float(params["start"][0]), float(params["end"][0])
        values = [
            [minute_end, str(row[field])]
            for row in self.metrics
            if row.get(field) is not None
            and start <= (minute_end := self._the_end_of(row)) <= end
        ]

        return {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [{"metric": {}, "values": values}] if values else []
            }
        }

    @staticmethod
    def _the_end_of(row: dict[str, object]) -> float:
        return (parse_iso(str(row["bucket_id"])) + timedelta(minutes=1)).timestamp()

    def _respond_with(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging


@pytest.fixture
def running_read_mcp() -> Iterator[type[FakeTargetServiceHandler]]:
    """Starts a fake Target Service (stdlib http.server, background thread,
    serving canned `/logs`, Prometheus's range query and
    `/argocd/<application>` JSON) plus a real `read_mcp_server` subprocess
    pointed at it - proves `read_mcp_client` reaches a real server without
    Docker or a real Target Service. Yields the handler class so a test can set
    `.logs`, `.metrics` and `.deploys` before calling through the client."""
    fake_target_service = HTTPServer(
        ("127.0.0.1", FAKE_TARGET_SERVICE_PORT), FakeTargetServiceHandler
    )
    server_thread = Thread(target=fake_target_service.serve_forever, daemon=True)
    server_thread.start()

    fake_target_service_url = f"http://127.0.0.1:{FAKE_TARGET_SERVICE_PORT}"
    env = os.environ.copy()
    env["TARGET_SERVICE_URL"] = fake_target_service_url
    # The change source and the metrics source are separate settings from the
    # Target Service's own URL - in production they are different systems
    # entirely - so the fake has to be named three times even though one
    # process answers all of them.
    env["ARGOCD_BASE_URL"] = fake_target_service_url
    env["PROMETHEUS_BASE_URL"] = f"{fake_target_service_url}{PROMETHEUS_PREFIX}"
    env["READ_MCP_HOST"] = "127.0.0.1"
    env["READ_MCP_PORT"] = str(READ_MCP_TEST_PORT)
    read_mcp_process = subprocess.Popen([sys.executable, "-m", "read_mcp_server.server"], env=env)

    os.environ["READ_MCP_HOST"] = env["READ_MCP_HOST"]
    os.environ["READ_MCP_PORT"] = env["READ_MCP_PORT"]
    get_settings.cache_clear()

    try:
        _wait_for_read_mcp()
        yield FakeTargetServiceHandler
    finally:
        read_mcp_process.terminate()
        read_mcp_process.wait(timeout=10)
        fake_target_service.shutdown()
        fake_target_service.server_close()
        server_thread.join()
        FakeTargetServiceHandler.logs = []
        FakeTargetServiceHandler.metrics = []
        FakeTargetServiceHandler.deploys = []
        del os.environ["READ_MCP_HOST"]
        del os.environ["READ_MCP_PORT"]
        get_settings.cache_clear()


def _wait_for_read_mcp(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{READ_MCP_TEST_PORT}/mcp", timeout=1.0)
            return
        except urllib.error.HTTPError:
            return  # a real HTTP response (even an error one) means the server is up
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise TimeoutError("read_mcp test server did not become ready within the timeout")
