"""Saying on a connection which claim of which run it writes for.

The kernel says what a claim is (`core.Fence`) and what holds one
(`core.Holding`); this is the database's half. A worker's connection carries its
fence in a session setting, and the schema's triggers refuse a write whose run
has since moved on, or a worker's write that names no run at all.
"""

from __future__ import annotations

from typing import Any, Final

import psycopg
from core import Fence, Holding
from psycopg_pool import ConnectionPool


def fence(conn: psycopg.Connection, held: Fence | None) -> None:
    """Says on `conn` which claim it writes for from now on, or that it writes
    for none.

    For the session rather than the transaction, and committed as it is said:
    the repositories commit as they go, and a fence that ended with the first of
    those - or was taken down by a rollback - would leave the writes after it
    made for no run at all.
    """
    conn.execute("SELECT set_config(%s, %s, false)",
                  (THE_FENCE, "" if held is None else held.spoken()))
    conn.commit()


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
        named = {**(pool.pop("kwargs", None) or {}), "application_name": A_WORKER}
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
# write from when it names no run. Public because the schema's fence spells it
# from here.
A_WORKER: Final = "argus-worker"

# The setting a connection's fence is said in, as `Fence.spoken` says it -
# read by the schema's fence, which spells it from here.
THE_FENCE: Final = "argus.fence"
