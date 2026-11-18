"""A connection that says each statement as it goes.

How the write tier keeps the connection it holds runs on: a run held for a
change is held by the session, not by a transaction, so nothing the tier holds
is a transaction in flight - which a claim would wait behind, and which the
event log would hold every incident's account back behind.
"""

from __future__ import annotations

import psycopg


def autocommitting(conn: psycopg.Connection) -> psycopg.Connection:
    """`conn`, committing each statement as it is said - opened with it, as
    `with autocommitting(connect_from_env()) as conn:`."""
    conn.autocommit = True

    return conn
