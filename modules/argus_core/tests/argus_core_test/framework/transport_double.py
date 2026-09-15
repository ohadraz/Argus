"""A one-tool MCP server the transport's own test starts, kills and restarts.

Two things in one file, because they are two halves of one fixture: the server
itself, which is run as `python -m argus_core_test.framework.transport_double`,
and the handle a test drives it by. It stands in for `argus-read-mcp` and
`argus-write-mcp` alike - neither is what the transport is about, and depending
on either would make the kernel's suite wait on an agent's server.

It is a real MCP server rather than a stub, because what is under test is the
session: an HTTP transport, an `initialize` handshake, and a server that can be
taken away underneath one. Nothing smaller can be wrong in the way this exists
to catch.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Self

from mcp.server.fastmcp import FastMCP

TRANSPORT_DOUBLE_PORT = 8194

STARTUP_TIMEOUT_SECONDS = 15.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
POLL_SECONDS = 0.2

# Counted in the server's own process, and asked for over MCP like anything
# else. It is what lets a test say a refusal was *not* retried: a client that
# quietly asked again would leave two here where the test made one call.
_times_refused = 0


def build_double(port: int) -> FastMCP:
    """The server: one tool that answers, one that refuses, one that counts."""
    server = FastMCP("transport-double", host="127.0.0.1", port=port)

    @server.tool()
    def say_something() -> list[str]:
        return ["something"]

    @server.tool()
    def refuse() -> list[str]:
        global _times_refused
        _times_refused += 1

        raise RuntimeError("this tool always refuses")

    @server.tool()
    def times_refused() -> int:
        return _times_refused

    @server.tool()
    async def dawdle(seconds: float) -> list[str]:
        """Still working when a test decides to close the client on it."""
        await asyncio.sleep(seconds)

        return ["eventually"]

    return server


class RunningDouble:
    """The double as a test drives it: up, down, and up again on the same port.

    Restarting on the same address is the whole point. A client holding a
    session to a server that went away has to notice and open another, and the
    only way to find out whether it does is to take the server away.
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        """Where the double serves MCP, in the form a client is given."""
        return f"http://127.0.0.1:{self._port}/mcp"

    def start(self) -> None:
        """Starts the server and waits until it is answering."""
        if self._process is not None:
            return

        self._process = subprocess.Popen(
            [sys.executable, "-m", __name__, str(self._port)],
            env={**os.environ, "PYTHONPATH": str(_suite_root())}
        )
        self._wait_until_listening()

    def stop(self) -> None:
        """Stops the server and waits for it to give the port back."""
        if self._process is None:
            return

        self._process.terminate()
        self._process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        self._process = None

    def restart(self) -> None:
        """Takes the server away and puts another in its place.

        The same address, a new process, and therefore no memory of any session
        a client still believes it holds.
        """
        self.stop()
        self.start()

    def __enter__(self) -> Self:
        self.start()

        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.stop()

    def _wait_until_listening(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(self.url, timeout=1.0)

                return
            except urllib.error.HTTPError:
                # A real HTTP response, even a refusing one, means it is up: a
                # bare GET is not a shape this endpoint serves.
                return
            except (urllib.error.URLError, ConnectionError):
                time.sleep(POLL_SECONDS)

        raise TimeoutError(
            f"the transport double at {self.url} did not answer within "
            f"{STARTUP_TIMEOUT_SECONDS} seconds"
        )


@contextmanager
def a_running_double(port: int = TRANSPORT_DOUBLE_PORT) -> Generator[RunningDouble]:
    """One double, running for the length of one test."""
    with RunningDouble(port) as double:
        yield double


def _suite_root() -> Path:
    """`modules/argus_core/tests`, which is what makes this importable by name.

    The suite is a package tree rather than an installed distribution, so a
    subprocess told to run one of its modules has to be told where the tree is.
    """
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    build_double(int(sys.argv[1])).run(transport="streamable-http")
