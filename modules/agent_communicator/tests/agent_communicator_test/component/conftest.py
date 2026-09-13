from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from slack_double import DEFAULT_BASE_URL, DEFAULT_PORT
from slack_double import app as slack_double_app

"""The Slack double, and nothing else.

A component test runs `agent_communicator` entire - the adapter, the client it
builds, the arguments the SDK encodes - and stands in for only what it cannot
be: Slack. The double is what the suites everywhere else already point at, so
what is exercised here is the same adapter the demo runs, reached the same way.

In a thread rather than a container, because it is a Python app and not a
service: the SDK needs a real port to talk to, and that is the whole of what
the double requires. Reset between tests for the reason the database is -
messages left by one test read back as another test's.
"""

_A_MOMENT = 0.05
_LONG_ENOUGH_TO_COME_UP = 10.0


@pytest.fixture(scope="session", autouse=True)
def slack() -> Iterator[str]:
    """The double, listening for the whole suite and stopped after it."""
    server = uvicorn.Server(
        uvicorn.Config(
            slack_double_app, host="localhost", port=DEFAULT_PORT, log_level="warning"
        )
    )
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    try:
        _once_it_answers()
        yield DEFAULT_BASE_URL
    finally:
        server.should_exit = True
        serving.join(timeout=_LONG_ENOUGH_TO_COME_UP)


@pytest.fixture(autouse=True)
def nothing_posted_yet(slack: str) -> None:
    """Empties the double, so each test reads back only its own messages."""
    httpx.post(f"{slack}/double-control/reset").raise_for_status()


def _once_it_answers() -> None:
    """Waits for the port, rather than guessing at how long a thread takes.

    A fixed sleep is either too short on a loaded machine - where the first
    test fails on a connection refused that says nothing about the code - or
    too long on every run that did not need it.
    """
    giving_up_at = time.monotonic() + _LONG_ENOUGH_TO_COME_UP
    while time.monotonic() < giving_up_at:
        try:
            httpx.get(f"{DEFAULT_BASE_URL}/health", timeout=_A_MOMENT).raise_for_status()
            return
        except (httpx.HTTPError, OSError):
            time.sleep(_A_MOMENT)

    raise RuntimeError(
        f"the slack double did not answer on {DEFAULT_BASE_URL} within "
        f"{_LONG_ENOUGH_TO_COME_UP:.0f}s"
    )
