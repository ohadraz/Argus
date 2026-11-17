"""A write made inside a transaction its caller then rolls back.

The repositories leave committing to whoever calls them, and this is how a suite
holds them to it: the write is made, the caller's transaction is rolled back, and
what the write would have changed is read afterwards. Whatever survived was
committed by the write itself.
"""

from __future__ import annotations

from collections.abc import Callable

import psycopg


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
