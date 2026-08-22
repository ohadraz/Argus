from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from argus_core.config import get_settings

FAKE_TARGET_SERVICE_PORT = 8180
READ_MCP_TEST_PORT = 8190


class FakeTargetServiceHandler(BaseHTTPRequestHandler):
    logs: list[str] = []
    metrics: list[dict[str, object]] = []

    def do_GET(self) -> None:
        if self.path in ("/logs", "/metrics"):
            payload = self.logs if self.path == "/logs" else self.metrics
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging


@pytest.fixture
def running_read_mcp() -> Iterator[type[FakeTargetServiceHandler]]:
    """Starts a fake Target Service (stdlib http.server, background thread,
    serving canned `/logs` and `/metrics` JSON) plus a real `read_mcp_server`
    subprocess pointed at it - proves `read_mcp_client` reaches a real server
    without Docker or a real Target Service. Yields the handler class so a
    test can set `.logs` and `.metrics` before calling through the client."""
    fake_target_service = HTTPServer(
        ("127.0.0.1", FAKE_TARGET_SERVICE_PORT), FakeTargetServiceHandler
    )
    server_thread = Thread(target=fake_target_service.serve_forever, daemon=True)
    server_thread.start()

    env = os.environ.copy()
    env["TARGET_SERVICE_URL"] = f"http://127.0.0.1:{FAKE_TARGET_SERVICE_PORT}"
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
