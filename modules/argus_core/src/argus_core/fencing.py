"""Keeping a walk whose run was taken back from acting as though it still held it.

A lease says when a worker may be presumed gone, and nothing stops a worker that
was only paused from carrying on once it wakes. Each claim of a run moves the
run's epoch on, so whatever that worker does after the run was taken back
carries an epoch the run no longer has - and what learns so says it here.

The database is what learns it. A worker's connection says which run and epoch
it writes for - its fence - and every table but the run's own refuses a write
whose run has since moved on, share-locking the run's row for the rest of the
transaction, so the run cannot be taken back under a write still being made. A
worker's connection that names no run is refused too: a walk writing for no run
is a worker that forgot to fence, and a fence nobody is made to put up is one a
stale walk gets round. Anything else - the web process, the relay, the schema
job - walks no run, and writes as it always did.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg_pool import ConnectionPool


class RunLost(Exception):
    """The run this process was walking is no longer its own.

    A newer claim holds it: the lease ran out while this process was paused,
    and another worker took the run back. Whatever this process does after
    learning so is a second walk of an incident somebody else is walking, so
    the one answer is to stop - nothing settled, nothing escalated, nothing put
    back.
    """


@dataclass(frozen=True)
class Fence:
    """Which claim of which run a connection writes for."""

    run_id: str
    epoch: int


class Holding:
    """The run this process is walking, as the claim it holds - or none, between
    runs.

    One per process rather than per thread: a walk is one run at a time, and its
    writes are made from threads it never sees - a checkpoint LangGraph saves in
    the background is as much the run's as a node's own.
    """

    def __init__(self) -> None:
        self._held: Fence | None = None

    def current(self) -> Fence | None:
        """The claim held now, or `None`."""
        return self._held

    @contextmanager
    def of(self, held: Fence) -> Iterator[None]:
        """`held` for as long as the block runs, and nothing after - however it
        ends."""
        self._held = held

        try:
            yield
        finally:
            self._held = None


def fence(conn: psycopg.Connection, held: Fence | None) -> None:
    """Says on `conn` which claim it writes for from now on, or that it writes
    for none.

    For the session rather than the transaction, and committed as it is said:
    the repositories commit as they go, and a fence that ended with the first of
    those - or was taken down by a rollback - would leave the writes after it
    made for no run at all.
    """
    conn.execute("SELECT set_config(%s, %s, false)",
                  (_THE_FENCE, "" if held is None else f"{held.run_id}:{held.epoch}"))
    conn.commit()


def was_lost(error: BaseException) -> bool:
    """Whether `error` says the run was lost, wherever it was said.

    Said by the walk as `RunLost`, or by the database as a refused write - and
    either may reach the caller inside something else that was raised while
    handling it, so the chain is followed to its end.
    """
    seen: set[int] = set()
    reached: BaseException | None = error

    while reached is not None and id(reached) not in seen:
        seen.add(id(reached))

        if isinstance(reached, RunLost) or (
            isinstance(reached, psycopg.Error) and reached.sqlstate == _RUN_LOST
        ):
            return True

        reached = reached.__cause__ or reached.__context__

    return False


class FencedPool(ConnectionPool):
    """A pool whose every connection is fenced with the run held as it is handed
    out.

    At the checkout rather than in a wrapper around `connection()`, because
    `getconn` is the other way out and `connection()` goes through it: a
    connection handed out by either carries the run held at that moment, and
    never the fence the last checkout left on it.

    Its connections are named as a worker's, which is what the database refuses
    an unfenced write by - so a pool that fences cannot hand out a connection
    whose forgotten fence goes unnoticed.
    """

    def __init__(self, conninfo: str, holding: Holding, **pool: Any) -> None:
        self._holding = holding
        named = {**(pool.pop("kwargs", None) or {}), "application_name": _A_WORKER}
        super().__init__(conninfo, kwargs=named, **pool)

    def getconn(self, timeout: float | None = None) -> Any:
        conn = super().getconn(timeout)

        try:
            fence(conn, self._holding.current())
        except BaseException:
            self.putconn(conn)
            raise

        return conn


# What a worker's connections are called, and so what the database refuses a
# write from when it names no run. The schema says the same word.
_A_WORKER: Final = "argus-worker"

# The setting a connection's fence is said in, as `<run id>:<epoch>`.
_THE_FENCE: Final = "argus.fence"

# The SQLSTATE a write is refused with when the run it was made for is another
# claim's now. Our own, in a class Postgres leaves unused; `AR002`, a worker
# writing for no run, is a bug rather than a lost run and is not answered here.
_RUN_LOST: Final = "AR001"
