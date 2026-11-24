"""Where connections come from, as a role built over them is handed them: one
that must never be opened, and one that counts how often it is.

What a role's `_over` form promises its caller is about opening: nothing when it
is built, and a connection of its own for each call. These say whether it kept
the promise.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager

import psycopg
from argus_testkit import Assertion
from postgres import Connections, connect_from_env


def connections_never_opened() -> Connections:
    """Connections that fail the test the moment anything opens one."""

    def opened() -> AbstractContextManager[psycopg.Connection]:
        raise AssertionError("Expected nothing to open a connection, and one was opened.")

    return opened


class CountedConnections:
    """Connections to the suite's database, counting each one opened."""

    def __init__(self) -> None:
        self.opened = 0

    @contextmanager
    def __call__(self) -> Iterator[psycopg.Connection]:
        self.opened += 1

        with connect_from_env() as conn:
            yield conn


def it_was_built() -> Assertion[object]:
    """That building the role gave back a role - which, handed connections
    that fail when opened, is building it opened nothing."""
    def assertion(built: object) -> bool:
        if built is None:
            raise AssertionError("Expected the role to be built, and nothing came back.")

        return True

    return assertion
