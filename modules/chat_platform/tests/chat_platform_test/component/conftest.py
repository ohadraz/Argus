"""The Slack double, and nothing else.

A component test runs the adapter entire - the client it builds, the arguments
the SDK encodes, the answer it parses - and stands in for only what it cannot
be: Slack. The double is what the suites everywhere else already point at, so
what is exercised here is the same adapter the demo runs, reached the same way.

In a thread rather than a container, because it is a Python app and not a
service: the SDK needs a real port to talk to, and that is the whole of what
the double requires. Emptied after each test so that messages left by one test
do not read back as another test's.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import httpx2
import pytest
import uvicorn
from slack_double import DEFAULT_BASE_URL, DEFAULT_PORT
from slack_double import app as slack_double_app

_A_MOMENT = 0.05
# How long the double has to answer before it is taken to hang. A guard against
# a hang and nothing tighter: a double that fails to start is seen ending and
# said at once, and a start on a machine every suite is loading at once takes
# many times what it takes on an idle one.
_LONG_PAST_ANY_START = 180.0
_LONG_ENOUGH_TO_STOP = 10.0


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
        _once_it_answers(serving)
        yield DEFAULT_BASE_URL
    finally:
        server.should_exit = True
        serving.join(timeout=_LONG_ENOUGH_TO_STOP)


@pytest.fixture(autouse=True)
def nothing_left_posted(slack: str) -> Iterator[None]:
    """Empties the double after each test, so the next reads back only its own
    messages.

    After rather than before, so a test leaves the double as it found it - the
    last test of the suite included - and what a failed test posted is still
    there to read while the failure is.
    """
    yield

    httpx2.post(f"{slack}/double-control/reset").raise_for_status()


def _once_it_answers(serving: threading.Thread) -> None:
    """Waits for the port, rather than guessing at how long a thread takes -
    and says at once that it will never answer where `serving` has ended.

    A fixed sleep is either too short on a loaded machine - where the first
    test fails on a connection refused that says nothing about the code - or
    too long on every run that did not need it.
    """
    giving_up_at = time.monotonic() + _LONG_PAST_ANY_START
    while time.monotonic() < giving_up_at:
        if not serving.is_alive():
            raise RuntimeError(
                f"the slack double stopped before it answered on {DEFAULT_BASE_URL}"
            )
        try:
            httpx2.get(f"{DEFAULT_BASE_URL}/health", timeout=_A_MOMENT).raise_for_status()
            return
        except (httpx2.HTTPError, OSError):
            time.sleep(_A_MOMENT)

    raise RuntimeError(
        f"the slack double did not answer on {DEFAULT_BASE_URL} within "
        f"{_LONG_PAST_ANY_START:.0f}s"
    )
