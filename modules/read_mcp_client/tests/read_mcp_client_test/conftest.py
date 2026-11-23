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
from typing import Final
from urllib.parse import parse_qs, urlsplit

import pytest
from alerting_platform.grafana import RULE_DEFINITION_PATH
from argus_testkit import a_free_port, refuse_the_e2e_stacks_project
from core import get_settings, parse_iso
from mcp.server.streamable_http import CONTENT_TYPE_JSON, CONTENT_TYPE_SSE
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    InitializeResult,
    JSONRPCRequest,
    JSONRPCResponse,
)
from metrics_source.prometheus_adapter import QUERIES
from postgres import connect_from_env, reset_schema

# The compose service the read server's database is, and what it stops.
_POSTGRES: Final = "postgres"
# What postgres depends on in docker-compose.yml, so `up` starts it with
# postgres and the stop names it too - or it outlives the suite.
_ITS_CLOCK: Final = "sim-clock"

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

# Who the read tier says it is when a session is opened over MCP: the name its
# server is built with. What a knock is answered with before the server counts
# as up - any other answer on the port is somebody else's.
THE_READ_TIER = "argus-read-mcp"
# Where it serves MCP, and the parts of the protocol a knock speaks: JSON-RPC's
# version, the one request's id, who is knocking, and the field of a
# server-sent event that carries the answer.
MCP_PATH: Final = "/mcp"
JSONRPC_VERSION: Final = "2.0"
A_KNOCK_ID = 1
THE_KNOCKER = Implementation(name="read-mcp-client-suite", version="0")
SSE_DATA_FIELD: Final = "data:"

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

# The account the read tier is told Argus signs in to the deployment platform
# as, so that what it says is Argus's is this suite's to say rather than the
# environment's.
ARGUS_S_ACCOUNT = "argus-in-the-suite"


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


@pytest.fixture(scope="session")
def postgres() -> Iterator[None]:
    """The read server's database, up for the whole suite with the schema
    applied, and stopped after it.

    The server refuses to start without one: its root opens its pool as it
    starts, and a pool refuses a database with no schema. Nothing here writes a
    row - the read tier writes none - so nothing is emptied between tests.

    Refused in the e2e stack's compose project, where the reset would empty the
    database a running stack's worker is attached to.
    """
    refuse_the_e2e_stacks_project("test_module(module='read_mcp_client')")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", _POSTGRES], check=True)
    try:
        with connect_from_env() as conn:
            reset_schema(conn)
        yield
    finally:
        subprocess.run(["docker", "compose", "stop", _POSTGRES, _ITS_CLOCK], check=True)


@pytest.fixture
def running_read_mcp(postgres: None) -> Iterator[type[FakeTargetServiceHandler]]:
    """Starts a fake Target Service (stdlib http.server, background thread,
    serving canned `/logs`, Prometheus's range query, Grafana's rule definitions,
    GitHub's comparisons and archives and `/argocd/<application>` JSON) plus a
    real `read_mcp_server` subprocess pointed at it - proves `read_mcp_client`
    reaches a real server without a real Target Service. The server's own
    database is real (`postgres`), since the server refuses to start without
    one. Yields the handler class so a test can set `.logs`, `.metrics`,
    `.deploys`, `.rules`, `.rule_queries`, `.tree`, `.comparisons` and
    `.archive` before calling through the client.

    The fake binds whatever port it is given and is asked which; the server
    is handed one the operating system just said was free, and counts as up
    only once it answers as the read tier on it."""
    fake_target_service = HTTPServer((LOOPBACK, ANY_FREE_PORT), FakeTargetServiceHandler)
    server_thread = Thread(target=fake_target_service.serve_forever, daemon=True)
    server_thread.start()

    fake_target_service_url = f"http://{LOOPBACK}:{fake_target_service.server_address[1]}"
    read_mcp_port = a_free_port()
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
    env["ARGOCD_ACTOR"] = ARGUS_S_ACCOUNT
    env["PROMETHEUS_BASE_URL"] = f"{fake_target_service_url}{PROMETHEUS_PREFIX}"
    env["GRAFANA_BASE_URL"] = f"{fake_target_service_url}{GRAFANA_PREFIX}"
    env["GITHUB_API_URL"] = f"{fake_target_service_url}{GITHUB_PREFIX}"
    env["READ_MCP_HOST"] = LOOPBACK
    env["READ_MCP_PORT"] = str(read_mcp_port)
    read_mcp_process = subprocess.Popen([sys.executable, "-m", "apps.read_mcp"], env=env)

    # Put back whole on the way out, so a variable that was set before keeps
    # its value rather than being deleted with the ones set here.
    the_environment_before = dict(os.environ)
    os.environ["READ_MCP_HOST"] = env["READ_MCP_HOST"]
    os.environ["READ_MCP_PORT"] = env["READ_MCP_PORT"]
    get_settings.cache_clear()

    try:
        _wait_for_read_mcp(read_mcp_process, f"http://{LOOPBACK}:{read_mcp_port}{MCP_PATH}")
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


def _wait_for_read_mcp(process: subprocess.Popen[bytes], url: str) -> None:
    """Waits until the server at `url` answers as the read tier, and says at
    once that it never will where its process has ended.

    As the read tier rather than at all: any other answer on the port says
    only that something is listening there - another copy of this suite's
    server, or one a killed run left behind - while this one may have failed to
    take the port, and will then be seen ending."""
    deadline = time.monotonic() + LONG_PAST_ANY_START_SECONDS
    while time.monotonic() < deadline:
        ended_with = process.poll()
        if ended_with is not None:
            raise RuntimeError(
                f"read_mcp test server ended with [{ended_with}] before it answered"
            )
        try:
            if _who_answers_at(url) == THE_READ_TIER:
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
        f"read_mcp test server did not answer within {LONG_PAST_ANY_START_SECONDS:.0f}s"
    )


def _who_answers_at(url: str) -> str:
    """The name the MCP server at `url` gives when a session is opened with it
    (`initialize`), answered as a server-sent event or as JSON - whichever the
    server chooses."""
    knock = InitializeRequest(params=InitializeRequestParams(
        protocolVersion=LATEST_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        clientInfo=THE_KNOCKER
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

    return InitializeResult.model_validate(response.result).serverInfo.name
