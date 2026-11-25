"""Every page read at one moment.

A page reads an incident several ways, and read at the database's own isolation
each would see whatever was committed when it ran: a page torn between two
moments. Every route that only reads takes its connections from `a_moment_of`;
what that hands out is `test_app.py`'s.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated

import psycopg
import pytest
from argus_testkit import Assertion, Scenario
from fastapi import Depends
from fastapi.testclient import TestClient
from postgres import Connections
from web_app.app import a_moment_of, connections_of

from web_app_test.framework.application import app

# An incident no row was ever written for: each page reads before it can say
# there is none, which is all these cases need it to do.
NO_SUCH_INCIDENT = "00000000-0000-4000-8000-000000000000"


@pytest.mark.component
@pytest.mark.parametrize("page", [
    "/",
    "/now",
    "/history",
    "/history/list",
    f"/incidents/{NO_SUCH_INCIDENT}",
    f"/incidents/{NO_SUCH_INCIDENT}/walk",
    f"/incidents/{NO_SUCH_INCIDENT}/postmortem",
    f"/incidents/{NO_SUCH_INCIDENT}/postmortem.pdf",
    f"/incidents/{NO_SUCH_INCIDENT}/synopsis.pdf"
])
def test_a_page_is_read_at_one_moment(page: str) -> None:
    entered: list[str] = []
    app.dependency_overrides[a_moment_of] = _a_moment_noted_in(entered)

    try:
        Scenario() \
            .when(
                lambda: _asked_for(page)
            ) \
            .then(
                _it_was_read_at_a_moment(entered)
            )
    finally:
        app.dependency_overrides.pop(a_moment_of, None)


def _a_moment_noted_in(entered: list[str]
                       ) -> Callable[[Connections], Connections]:
    """A stand-in for `a_moment_of`, built on the app's own connections, that
    notes each connection it hands out in `entered`."""
    def a_moment(connections: Annotated[Connections, Depends(connections_of)]) -> Connections:
        @contextmanager
        def noted() -> Iterator[psycopg.Connection]:
            entered.append("entered")
            with connections() as conn:
                yield conn

        return noted

    return a_moment


def _asked_for(page: str) -> int:
    """The status `page` answered with - what it says is other suites'."""
    with TestClient(app) as client:
        return client.get(page).status_code


def _it_was_read_at_a_moment(entered: list[str]) -> Assertion[int]:
    def assertion(status: int) -> bool:
        if not entered:
            raise AssertionError(
                f"Expected the page read on a connection from `a_moment_of`, and it "
                f"answered [{status}] having taken none."
            )

        return True

    return assertion
