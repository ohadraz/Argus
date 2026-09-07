from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

import psycopg
from psycopg_pool import ConnectionPool

from argus_core.config import get_settings

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


def open_pool() -> ConnectionPool:
    """A pool, open and ready, for a process that will own it.

    Returned open rather than left to the caller, so that a process holding one
    cannot be a process that forgot to open it. Closing is the owner's, at the
    end of the lifespan that opened it.

    Every connection is checked on the way out, which a bare `connect` never had
    to be: a pooled connection outlives the server restarting, and the one thing
    worse than paying for a handshake is handing out a socket to a Postgres that
    is no longer on the other end of it.
    """
    return ConnectionPool(get_settings().database_url,
                          min_size=_MIN_CONNECTIONS,
                          max_size=_MAX_CONNECTIONS,
                          check=ConnectionPool.check_connection,
                          open=True)


def connect() -> psycopg.Connection:
    """One connection, opened now and closed by whoever asked for it.

    For a caller whose whole life is shorter than a pool would be worth: a
    migration script, a suite arranging a row, a one-shot command. A long-lived
    process wants `open_pool` instead.
    """
    return psycopg.connect(get_settings().database_url)
