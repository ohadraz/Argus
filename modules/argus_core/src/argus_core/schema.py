from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Final

import psycopg
from alembic import command
from alembic.config import Config

from argus_core.db import connect

logger = logging.getLogger(__name__)

"""Who applies Argus's schema, and what a process that finds none does about it.

The schema is Alembic's, in `migrations/versions/` - `001` is every table there
is, and the alters will be `002` onwards. Applied from here and from nowhere
else: no process that serves requests or drains work touches DDL, so the order
the stack comes up in is nobody's promise to keep.

Applied by replacing, for now. The chain is run against a database that was just
dropped, which is why `001` can still be edited as though the schema had always
said what it now says - a licence that lasts exactly as long as no deployment
outlives a restart, and no longer.
"""


def _upgrade_to_head() -> None:
    """Runs the chain, from wherever the database is to wherever it ends.

    Takes no connection and opens its own. Alembic wants a SQLAlchemy connection
    where every caller here holds a psycopg one, and the wrapping that would
    bridge them buys nothing: `env.py` reads the same `Settings` those
    connections are opened from, so the two cannot be different databases.

    The configuration is built here rather than read from `alembic.ini`, so that
    the chain is found by the package's own location. A deployment that
    installed `argus_core` and never checked this repo out still has its
    migrations; `alembic.ini` exists for the command line, which does not.
    """
    config = Config()
    config.set_main_option("script_location", str(_THE_MIGRATIONS))
    command.upgrade(config, _THE_LATEST_REVISION)


class SchemaNotApplied(Exception):
    """What a process raises rather than run against a database nobody prepared."""


type SchemaPresent = Callable[[psycopg.Connection], bool]


def schema_is_present(conn: psycopg.Connection) -> bool:
    """Whether this database has had the schema applied to it.

    One table is asked after, because the DDL is applied as a single statement
    in a single transaction: there is no state in which half of it exists, so a
    second question would have exactly one possible answer.

    `to_regclass` rather than a query against the table, because a name that
    resolves to nothing is an answer here and an error there - and an error
    would have to be caught by class and matched by message to be told apart
    from the database being unreachable, which is not the same problem at all.
    """
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT to_regclass('{_THE_WITNESS_TABLE}') IS NOT NULL")
        row = cursor.fetchone()

    return bool(row is not None and row[0])


def require_schema(conn: psycopg.Connection,
                   present: SchemaPresent = schema_is_present) -> None:
    """Refuses to go on against a database with no schema, naming the fix.

    What every process that holds a connection calls before it serves or drains
    anything. Argus applies its schema from a job of its own, so a process that
    finds none has been started out of order rather than found a fault - and the
    useful thing to say is the command, not the condition. `no such table:
    incident`, arriving on whatever route is hit first, sends a reader to the
    schema instead of to the job.

    The asking is injected because whether the tables are there is a question
    for a database and whether an answer of "no" is fatal is not. Only the first
    needs a container.
    """
    if not present(conn):
        raise SchemaNotApplied(
            f"this database has no Argus schema - apply it with "
            f"`uv run python -m {_THE_JOB}`"
        )


def reset_schema(conn: psycopg.Connection) -> None:
    """Throws the schema away and runs the chain against what is left.

    The only way the schema is ever applied - by the job below, and by every
    suite on its way in. The drop goes first while `001` is still the whole
    chain: a revision that has only ever run against an empty database is one
    that can be edited, and the drop is what keeps that true. It goes when the
    first `002` lands, and this becomes an upgrade like any other.

    Dropping takes `alembic_version` with it, which is the point: the chain is
    then applied from nothing rather than found to be already at head.

    It empties the tables as a consequence, which is the other half. Emptying
    between tests happens *after* each test, so that a failure leaves its rows
    to be read - which means a run that was killed leaves its last test's rows
    for the next run's first test to find. Starting from nothing is what makes
    the manner of the previous run's death stop mattering.

    Here rather than in a conftest because naming the schema is exactly what
    this exists to spare its callers, and four suites naming it would be four
    places to fix on the day it is no longer `public`.

    Bounded by a lock timeout, because the drop waits for whatever holds a
    table rather than failing on it. Anything still connected to an adopted
    container - a worker a killed run left behind, a suite someone started in
    another terminal - would otherwise stop this at the first statement of a
    session-scoped fixture, before pytest has printed a line, and a run hung
    with no output is the hardest kind of failure to place. Given a bound it
    says which statement waited and for how long.
    """
    with conn.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{_SECONDS_TO_WAIT_FOR_A_LOCK}s'")
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")
    conn.commit()

    _upgrade_to_head()


def main() -> None:
    """The job: the schema, applied to the database `Settings` names.

    A module entry point rather than a nox session's body, because the same act
    is wanted from three places that are not all nox - a local checkout, the e2e
    stack, and whatever brings this up the day the services are containerized.
    `nox -s schema` calls this; it does not reimplement it.

    Says which database it applied to, and not how it reached it: the URL
    carries a password, and a job whose ordinary output is a credential is a job
    whose output nobody can paste into an issue.
    """
    logging.basicConfig(level=logging.INFO)

    with connect() as conn:
        reset_schema(conn)
        logger.info("schema applied to %s on %s:%s",
                    conn.info.dbname, conn.info.host, conn.info.port)


# How long the reset waits for a table somebody else is holding. Long enough
# to outlast a connection on its way out - a process that has just been killed
# still holds its locks until the server notices - and short enough that a
# suite blocked behind a live one reports it while somebody is still watching.
_SECONDS_TO_WAIT_FOR_A_LOCK: Final = 10

# The table a process asks after to learn whether the schema is there. The first
# one `001` declares and the one every other table hangs off, so a database that
# has it has all of them. Not `alembic_version`, which says a chain ran and not
# what it left.
_THE_WITNESS_TABLE: Final = "incident"

# Where the chain lives, found from this package rather than from a checkout -
# `alembic.ini` says the same thing for the command line's benefit, and is the
# copy that goes stale if these ever disagree.
_THE_MIGRATIONS: Final = Path(__file__).parent / "migrations"

# As far as the chain goes. Alembic's own word for it, named because it is the
# vocabulary of a tool rather than a sentence of ours.
_THE_LATEST_REVISION: Final = "head"

# How a process tells somebody to apply the schema. Named here because the two
# processes that refuse would otherwise each write their own version of one
# sentence, and the sentence is the whole value of the refusal.
_THE_JOB: Final = "nox -s schema"


if __name__ == "__main__":
    main()
