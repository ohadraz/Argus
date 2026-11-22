"""Where a connection to Argus's own database comes from.

Two things live here, for two kinds of caller. A process that runs for a while -
the web application, the worker - owns a pool and hands out connections from it,
because an incident opens dozens and the handshake is the part worth not paying
for. Something that owns its own short life - a script, a suite setting up a row
- opens one connection and closes it.

Neither is reached for. What a component needs is a way to get a connection, and
it is given one: `Connections` is that, and both a pool's `connection` and the
bare `connect` below satisfy it. Nothing below the process edge knows which it
was handed, which is what keeps `psycopg_pool` out of every module that happens
to write a row.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import psycopg
from core import DatabaseSettings, Holding, get_settings
from psycopg_pool import ConnectionPool

from postgres.fencing import FencedPool
from postgres.schema import require_schema

# How anything gets a connection: ask, use it for a block, and let go. The
# narrowest thing a caller can depend on, and deliberately not `ConnectionPool` -
# a repository that took a pool would be a repository that cannot be handed a
# single connection.
type Connections = Callable[[], AbstractContextManager[psycopg.Connection]]

# One connection is the resting state - a worker between runs, a web process
# nobody is asking anything of - and the ceiling is what a single walk holds at
# once: the run's own connection, the repository call inside a node, and the
# event that call publishes, with room left over for a second walker.
_MIN_CONNECTIONS = 1
_MAX_CONNECTIONS = 10


def open_pool(settings: DatabaseSettings,
              holding: Holding | None = None,
              connection: Mapping[str, Any] | None = None) -> ConnectionPool:
    """A pool, open and ready, for a process that will own it.

    Returned open rather than left to the caller, so that a process holding one
    cannot be a process that forgot to open it. Closing is the owner's, at the
    end of the lifespan that opened it.

    Every connection is checked on the way out, which a bare `connect` never had
    to be: a pooled connection outlives the server restarting, and the one thing
    worse than paying for a handshake is handing out a socket to a Postgres that
    is no longer on the other end of it.

    A process that walks runs hands over what it is `holding`, and every
    connection is fenced with it as it goes out (`postgres.fencing`). What a
    `connection` must be like - the checkpointer's commit as they go - is the
    caller's to say, and applies to every one.

    Refused where the database has no schema (`SchemaNotApplied`), asked on one
    of the pool's own connections before the pool is handed back. Every
    process that holds a pool opens it on the way up, so here the check is
    made for all of them, and a process added later cannot forget it. The pool
    is closed on the way out of any failure to ask - a refusal, or a database
    that never answered: nobody owns a pool that was not handed back, and one
    left open would go on holding its connections.
    """
    pool: dict[str, Any] = {"min_size": _MIN_CONNECTIONS,
                            "max_size": _MAX_CONNECTIONS,
                            "check": ConnectionPool.check_connection,
                            "kwargs": dict(connection or {}),
                            "open": True}

    opened = (ConnectionPool(settings.database_url, **pool) if holding is None
              else FencedPool(settings.database_url, holding, **pool))

    try:
        with opened.connection() as conn:
            require_schema(conn)
    except BaseException:
        opened.close()
        raise

    return opened


@contextmanager
def unit_of_work(connections: Connections) -> Iterator[psycopg.Connection]:
    """One connection holding one transaction, committed when the block ends
    and rolled back if it raises.

    The caller's, never a repository's. A repository function writes and
    leaves committing alone, so several of them can be one operation - an
    incident and the run that walks it, a status and the line saying so - and
    a failure part-way through undoes all of it rather than the half that came
    after the last commit.

    A transaction rather than the connection's own commit on leaving the block,
    because inside one a `commit()` is refused: a write that tried to commit on
    its own would make part of the unit permanent whatever became of the rest,
    and the refusal says so at the first call rather than in production.
    """
    with connections() as conn, conn.transaction():
        yield conn


def connect(settings: DatabaseSettings,
            connection: Mapping[str, Any] | None = None) -> psycopg.Connection:
    """One connection, opened now and closed by whoever asked for it.

    For a caller whose whole life is shorter than a pool would be worth: a
    migration script, a suite arranging a row, a one-shot command - or one whose
    closing is the point, as a run held for a change is let go by closing the
    connection that held it. A long-lived process wants `open_pool` instead.

    What the `connection` must be like is the caller's to say, as `open_pool`'s
    is.
    """
    return psycopg.connect(settings.database_url, **dict(connection or {}))


def require_schema_at(settings: DatabaseSettings) -> None:
    """Refuses to go on against a database with no schema, asked on a
    connection opened for the question and closed after it.

    For a process that holds no pool, and so is not checked by opening one: the
    write tier opens a connection per change, and would otherwise learn of a
    missing schema at its first change, in the middle of an incident.
    """
    with connect(settings) as conn:
        require_schema(conn)


def connect_from_env() -> psycopg.Connection:
    """One connection, to whichever database the environment names.

    The ambient read, spelled out. A script, a suite or a one-shot command has
    no composition root to be handed a slice by, and pretending otherwise would
    only hide the read inside `connect` where nothing could find it. Named so
    that grepping for who reads the environment finds every one of them.
    """
    return connect(DatabaseSettings.of(get_settings()))
