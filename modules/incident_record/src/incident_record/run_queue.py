"""The queue between the process that accepts an alert and the process that
walks it: claiming a run, keeping it, settling it, and holding it while the
write tier makes a change for it.

On a connection its caller holds, and never anything else. The queue is driven
inside the caller's own transaction - a run settled with its claims settled
beside it, a change made only while the connection holding the run stays open -
so a queue that opened connections of its own would be one whose writes landed
apart from the decisions they belong to.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from typing import Protocol

import psycopg
from core import Fence

from incident_record.repository import incidents, runs, taken_actions
from incident_record.repository.runs import Run
from incident_record.repository.taken_actions import NoLongerOpen


class RunQueue(Protocol):
    """The incident runs, as the processes that walk them and change the world
    for them hold them."""

    def claim(self, claimed_by: str, lease: timedelta, /) -> Run | None:
        """The next run there is to walk, claimed for `claimed_by` for `lease`,
        or `None` where there is none."""
        ...

    def renew(self, held: Run, lease: timedelta, /) -> bool:
        """Whether the run is still the claim's, its lease renewed if so."""
        ...

    def finish(self, held: Run, /) -> bool:
        """Settles the run as walked to its end, where the claim still holds it."""
        ...

    def fail(self, held: Run, reason: str, /) -> bool:
        """Settles the run as failed, for `reason`, where the claim still holds it."""
        ...

    def try_again_later(self, held: Run, wait: timedelta, /) -> bool:
        """Puts the run back to be taken again after `wait`, where the claim
        still holds it."""
        ...

    def hold_for_a_change(self, held: Fence, /) -> AbstractContextManager[bool]:
        """Holds the run while a change is made for it, saying whether the claim
        still holds it."""
        ...

    def escalate_unless_ended(self, incident_id: str, /, *, at: datetime) -> bool:
        """Moves an incident whose walk stopped without finishing to escalated,
        unless it already ended."""
        ...

    def settle_claims(self, incident_id: str, /) -> None:
        """Settles every claim the incident's walk left open."""
        ...

    def no_longer_open(self, incident_id: str, at: datetime, /, *,
                       which: NoLongerOpen) -> None:
        """Closes on their subjects the incident's changes that `which` names."""
        ...


class _OnAConnection:
    """The queue, on a connection somebody else holds and commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def claim(self, claimed_by: str, lease: timedelta, /) -> Run | None:
        return runs.claim(self._conn, claimed_by, lease)

    def renew(self, held: Run, lease: timedelta, /) -> bool:
        return runs.renew(self._conn, held, lease)

    def finish(self, held: Run, /) -> bool:
        return runs.finish(self._conn, held)

    def fail(self, held: Run, reason: str, /) -> bool:
        return runs.fail(self._conn, held, reason)

    def try_again_later(self, held: Run, wait: timedelta, /) -> bool:
        return runs.try_again_later(self._conn, held, wait)

    @contextmanager
    def hold_for_a_change(self, held: Fence, /) -> Iterator[bool]:
        with runs.hold_for_a_change(self._conn, held) as holds:
            yield holds

    def escalate_unless_ended(self, incident_id: str, /, *, at: datetime) -> bool:
        return incidents.escalate_unless_ended(self._conn, incident_id, at=at)

    def settle_claims(self, incident_id: str, /) -> None:
        taken_actions.settle_claims(self._conn, incident_id)

    def no_longer_open(self, incident_id: str, at: datetime, /, *,
                       which: NoLongerOpen) -> None:
        taken_actions.no_longer_open(self._conn, incident_id, at, which=which)


def run_queue_on(conn: psycopg.Connection) -> RunQueue:
    """The queue, on `conn`, which the caller holds and commits - and whose
    fence every write made through it carries."""
    return _OnAConnection(conn)
