from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import pytest
from core import get_settings, parse_iso
from metrics_source.prometheus_adapter import QUERIES
from read_mcp_server.alert_rules import RULE_DEFINITION_PATH

FAKE_TARGET_SERVICE_PORT = 8180
READ_MCP_TEST_PORT = 8190
# How long a started server has to answer before it is taken to hang. A guard
# against a hang and nothing tighter: a server that fails to start is seen
# exiting and said at once, and with every suite running at once a start that
# takes three seconds idle has been measured at over fifteen.
LONG_PAST_ANY_START_SECONDS = 180.0
A_MOMENT_BETWEEN_KNOCKS_SECONDS = 0.2

# Where the fake answers as Prometheus: under a prefix, the way the Target
# Environment's own stand-in does, so the setting carries a path and the
# adapter's own path is appended to it.
PROMETHEUS_PREFIX = "/prometheus"
THE_RANGE_QUERY_PATH = f"{PROMETHEUS_PREFIX}/api/v1/query_range"

# Which bucket field each query asks for - the inverse of what the adapter asks.
FIELD_ASKED_BY = {query: field for field, query in QUERIES.items()}

# Where the fake answers as Grafana, under a prefix for the reason Prometheus is,
# and the provisioning API's route for one rule's definition beneath it - the
# route the server asks, less the rule it fills in.
GRAFANA_PREFIX = "/grafana"
RULE_DEFINITION_PREFIX = f"{GRAFANA_PREFIX}{RULE_DEFINITION_PATH.removesuffix('{rule}')}"

# Where the fake answers as GitHub, under a prefix for the reason Prometheus is,
# the part of a comparison's path that names its two commits, and the part of an
# archive's path that names the ref it was cut at.
GITHUB_PREFIX = "/github"
COMPARISON_MARK = "/compare/"
ARCHIVE_MARK = "/tarball/"

# The directory GitHub wraps every entry of an archive in, named for the owner,
# the repository and the commit.
ARCHIVE_ROOT = "owner-repo-77296ac"


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
    # Alert rule definitions by uid, in Grafana's provisioning shape, and the
    # queries those definitions name beyond the adapter's own - each mapped to
    # the row field that answers it, so a rule's series is served from the same
    # rows as everything else.
    rules: dict[str, dict[str, object]] = {}
    rule_queries: dict[str, str] = {}
    # One application's resource tree, in Argo CD's own wire shape: its pods
    # with the node each runs on, and the nodes with their labels.
    tree: dict[str, object] = {}
    # How the second commit of each comparison stands to the first, by the
    # `base...head` the comparison names, in GitHub's own words.
    comparisons: dict[str, str] = {}
    # What the repository holds at any ref, by path - served as GitHub serves an
    # archive, gzipped and wrapped in a directory of its own.
    archive: dict[str, str] = {}

    def do_GET(self) -> None:
        url = urlsplit(self.path)

        if url.path == "/logs":
            self._respond_with(self.logs)
        elif url.path == THE_RANGE_QUERY_PATH:
            self._respond_with(self._a_matrix(parse_qs(url.query)))
        elif url.path.startswith(RULE_DEFINITION_PREFIX):
            rule = url.path.removeprefix(RULE_DEFINITION_PREFIX)

            if rule in self.rules:
                self._respond_with(self.rules[rule])
            else:
                self.send_response(404)
                self.end_headers()
        elif url.path.startswith(GITHUB_PREFIX) and COMPARISON_MARK in url.path:
            basehead = url.path.partition(COMPARISON_MARK)[2]

            if basehead in self.comparisons:
                self._respond_with({"status": self.comparisons[basehead], "files": []})
            else:
                self.send_response(404)
                self.end_headers()
        elif url.path.startswith(GITHUB_PREFIX) and ARCHIVE_MARK in url.path:
            self._respond_with_bytes(self._a_tarball(self.archive), "application/x-gzip")
        elif url.path.startswith("/argocd/") and url.path.endswith("/resource-tree"):
            self._respond_with(self.tree)
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
        query = params["query"][0]
        field = FIELD_ASKED_BY.get(query) or self.rule_queries[query]
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

    @staticmethod
    def _a_tarball(files: dict[str, str]) -> bytes:
        """`files` as GitHub archives a repository: gzipped, every entry under a
        directory named for the commit."""
        buffer = io.BytesIO()

        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for path, text in files.items():
                data = text.encode()
                entry = tarfile.TarInfo(f"{ARCHIVE_ROOT}/{path}")
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

        return buffer.getvalue()

    def _respond_with(self, payload: object) -> None:
        self._respond_with_bytes(json.dumps(payload).encode(), "application/json")

    def _respond_with_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging


@pytest.fixture
def running_read_mcp() -> Iterator[type[FakeTargetServiceHandler]]:
    """Starts a fake Target Service (stdlib http.server, background thread,
    serving canned `/logs`, Prometheus's range query, Grafana's rule definitions,
    GitHub's comparisons and archives and `/argocd/<application>` JSON) plus a
    real `read_mcp_server` subprocess pointed at it - proves `read_mcp_client`
    reaches a real server without Docker or a real Target Service. Yields the
    handler class so a test can set `.logs`, `.metrics`, `.deploys`, `.rules`,
    `.rule_queries`, `.tree`, `.comparisons` and `.archive` before calling
    through the client."""
    fake_target_service = HTTPServer(
        ("127.0.0.1", FAKE_TARGET_SERVICE_PORT), FakeTargetServiceHandler
    )
    server_thread = Thread(target=fake_target_service.serve_forever, daemon=True)
    server_thread.start()

    fake_target_service_url = f"http://127.0.0.1:{FAKE_TARGET_SERVICE_PORT}"
    env = os.environ.copy()
    # Somewhere of its own, so a suite never writes into the repository's
    # telemetry directory.
    telemetry = TemporaryDirectory(prefix="argus-telemetry-", ignore_cleanup_errors=True)
    env["TELEMETRY_DIRECTORY"] = telemetry.name
    env["TARGET_SERVICE_URL"] = fake_target_service_url
    # The change source and the metrics source are separate settings from the
    # Target Service's own URL - in production they are different systems
    # entirely - so the fake has to be named three times even though one
    # process answers all of them.
    env["ARGOCD_BASE_URL"] = fake_target_service_url
    env["PROMETHEUS_BASE_URL"] = f"{fake_target_service_url}{PROMETHEUS_PREFIX}"
    env["GRAFANA_BASE_URL"] = f"{fake_target_service_url}{GRAFANA_PREFIX}"
    env["GITHUB_API_URL"] = f"{fake_target_service_url}{GITHUB_PREFIX}"
    env["READ_MCP_HOST"] = "127.0.0.1"
    env["READ_MCP_PORT"] = str(READ_MCP_TEST_PORT)
    read_mcp_process = subprocess.Popen([sys.executable, "-m", "read_mcp_server.server"], env=env)

    # Put back whole on the way out, so a variable that was set before keeps
    # its value rather than being deleted with the ones set here.
    the_environment_before = dict(os.environ)
    os.environ["READ_MCP_HOST"] = env["READ_MCP_HOST"]
    os.environ["READ_MCP_PORT"] = env["READ_MCP_PORT"]
    get_settings.cache_clear()

    try:
        _wait_for_read_mcp(read_mcp_process)
        yield FakeTargetServiceHandler
    finally:
        read_mcp_process.terminate()
        read_mcp_process.wait(timeout=10)
        telemetry.cleanup()
        fake_target_service.shutdown()
        fake_target_service.server_close()
        server_thread.join()
        FakeTargetServiceHandler.logs = []
        FakeTargetServiceHandler.metrics = []
        FakeTargetServiceHandler.deploys = []
        FakeTargetServiceHandler.rules = {}
        FakeTargetServiceHandler.rule_queries = {}
        FakeTargetServiceHandler.tree = {}
        FakeTargetServiceHandler.comparisons = {}
        FakeTargetServiceHandler.archive = {}
        os.environ.clear()
        os.environ.update(the_environment_before)
        get_settings.cache_clear()


def _wait_for_read_mcp(process: subprocess.Popen[bytes]) -> None:
    """Waits until the server answers, and says at once that it never will
    where its process has ended."""
    deadline = time.monotonic() + LONG_PAST_ANY_START_SECONDS
    while time.monotonic() < deadline:
        ended_with = process.poll()
        if ended_with is not None:
            raise RuntimeError(
                f"read_mcp test server ended with [{ended_with}] before it answered"
            )
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{READ_MCP_TEST_PORT}/mcp", timeout=1.0)
            return
        except urllib.error.HTTPError:
            return  # a real HTTP response (even an error one) means the server is up
        except OSError:
            # Not answering yet: refused, or taken and not answered within the
            # knock's second - which `urlopen` raises bare, not as a `URLError`.
            time.sleep(A_MOMENT_BETWEEN_KNOCKS_SECONDS)
    raise TimeoutError(
        f"read_mcp test server did not answer within {LONG_PAST_ANY_START_SECONDS:.0f}s"
    )
