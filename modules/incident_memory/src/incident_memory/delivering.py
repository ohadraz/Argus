"""Carrying what walks filed into the store a later walk searches (spec §11.2).

The store is a view of the filed rows, not a record of its own. A walk files a
row the fence can refuse (`filing`) and never touches the store; this process,
which walks no run, reads the rows the store does not hold yet, keeps each one
there (`keeping`), and marks the version it kept. The difference between the
version filed and the version delivered is the work list and the retry - a pass
that failed leaves it where it was, so the next pass finds the same records
waiting, and a deliverer that was down catches up on everything it missed.

One deliverer at a time. Two at once can leave the store holding an older
record for good: one reads a version, the walk refiles, the other delivers the
newer one, and the first then writes the older one over it - its mark, for a
version already passed, changing nothing. So each pass is made holding a lock
in the database on a connection of its own, and a second deliverer that finds
it held waits for its next interval. Not a lock on the rows: that would make a
walk refiling a record wait on the store.

The process itself - its pool, the store's adapter, the embedder - is built by
its root, `apps.deliverer`, and handed in: what `keeping` writes through is the
port, and nothing here names the vendor.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Final, Protocol

import psycopg

from incident_memory.filing import get_undelivered, record_delivered
from incident_memory.keeping import Keeper

logger = logging.getLogger(__name__)

# How many records one pass embeds before it marks them. A deliverer that fell
# behind by a thousand incidents catches up a batch at a time, and a pass that
# fails part of the way through loses at most this much work.
A_BATCH: Final = 100

# The lock a pass is made holding, as Postgres names an advisory lock: a number
# of the application's choosing. Arbitrary, and fixed - every deliverer has to
# ask for the same one.
_THE_DELIVERY: Final = 7_111_002

# How the wait between passes is spent. Injected so that a loop which never
# returns can still be driven by a test, through a sleep that ends it.
Sleeper = Callable[[float], None]


class Pass(Protocol):
    """One delivery pass, with everything it needs already bound to it."""

    def __call__(self) -> int: ...


@contextmanager
def holding_the_delivery(conn: psycopg.Connection) -> Generator[bool]:
    """Whether this connection holds the delivery for the block - and, if it
    does, gives it back however the block ends.

    For the session rather than a transaction, because the reads and marks
    inside commit as they go and a transaction's lock would go with the first
    of them. Asked for rather than waited on: a second deliverer has nothing to
    do that the first is not already doing, and its next interval is soon.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (_THE_DELIVERY,))
        held = cursor.fetchone()

    conn.commit()
    ours = held is not None and bool(held[0])

    try:
        yield ours
    finally:
        if ours:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_THE_DELIVERY,))
            conn.commit()


def deliver_on(conn: psycopg.Connection, keep: Keeper, *, batch: int = A_BATCH) -> int:
    """Delivers what is waiting, a batch of it, and answers how many.

    Nothing where another deliverer holds the delivery. Each record is kept and
    then marked, in that order, so a record is only ever marked once the store
    holds it - and a pass that fails part of the way leaves the rest waiting.

    Raises whatever the store or the database raised. A failure must leave the
    record waiting: swallowing it here would hand the next pass a row that
    looks delivered and a store that never saw it.
    """
    with holding_the_delivery(conn) as ours:
        if not ours:
            return 0

        waiting = get_undelivered(conn, batch)

        for filed in waiting:
            keep(filed.record)
            record_delivered(conn, filed.record.incident_id, filed.version)

    if waiting:
        logger.info("records delivered", extra={"records": len(waiting)})

    return len(waiting)


def deliver_forever(interval_seconds: float,
                    pass_over: Pass,
                    *,
                    sleep: Sleeper = time.sleep) -> None:
    """Delivers for as long as the process lives, waking on its own schedule.

    A pass that raised is logged and slept off rather than ending the process.
    What it did not deliver is still waiting, so the next wake-up is the retry
    - where a crash loop would have the process restart faster than the store
    recovers. A warning rather than an error for the same reason: nobody has to
    act, and nothing a walk waits on is behind it.
    """
    while True:
        try:
            pass_over()
        except Exception:
            logger.warning("delivery pass failed", exc_info=True)

        sleep(interval_seconds)
