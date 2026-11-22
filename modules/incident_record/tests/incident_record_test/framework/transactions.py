"""Transactions as a suite needs to see them: a write made inside one its
caller then rolls back, and an account written inside one, as seen from within
it and from outside it.

The repositories leave committing to whoever calls them, and the first is how a
suite holds them to it: the write is made, the caller's transaction is rolled
back, and what the write would have changed is read afterwards. Whatever
survived was committed by the write itself.

The operations above the repositories write a change and its account in one
transaction, and the rest is how a suite holds them to that: what the account's
writer could see when it wrote, and an account that fails on the connection it
was handed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from core.events import IncidentEvent, Publisher
from core.models import IncidentStatus
from incident_record import PublisherFor
from incident_record.repository import incidents
from postgres import connect_from_env


def written_and_rolled_back(conn: psycopg.Connection,
                            write: Callable[[], object]) -> Callable[[], None]:
    """`write`, made inside a transaction on `conn` that its caller then rolls
    back - a `given` step, for a case that reads back what the write would have
    changed.

    A write that survives this committed on its own, so no caller can make it
    part of anything larger: whatever the caller writes beside it, a failure
    between the two leaves one without the other. psycopg refuses a `commit()`
    inside `conn.transaction()` outright, so such a write fails here rather than
    surviving it.

    Rows written earlier on `conn` are kept. With a transaction already open,
    `conn.transaction()` is a savepoint, and the rollback undoes only what was
    written inside it.
    """
    def step() -> None:
        with conn.transaction():
            write()
            raise psycopg.Rollback()

    return step


@dataclass(frozen=True)
class Seen:
    """An incident's status at the moment its account was written: on the
    connection writing it, and on one of its own."""

    inside: IncidentStatus | None
    outside: IncidentStatus | None


def seen_from_both_sides(seen: list[Seen], incident_id: str) -> PublisherFor:
    """A publisher that, as each account is written, notes the incident's
    status where it is written and from a connection of its own.

    Both are plain reads, so the one from outside cannot wait behind the change
    it is looking past.
    """
    def publisher_for(conn: psycopg.Connection) -> Publisher:
        def publisher(_event: IncidentEvent) -> None:
            inside = incidents.get(conn, incident_id)

            with connect_from_env() as elsewhere:
                outside = incidents.get(elsewhere, incident_id)

            seen.append(Seen(inside=inside.status if inside is not None else None,
                             outside=outside.status if outside is not None else None))

        return publisher

    return publisher_for


def failing_on_its_connection(conn: psycopg.Connection) -> Publisher:
    """A publisher whose every account fails on the connection it was handed -
    which, without a savepoint around it, aborts whatever that connection was
    in the middle of."""
    def publisher(_event: IncidentEvent) -> None:
        conn.execute("SELECT 1/0")

    return publisher
