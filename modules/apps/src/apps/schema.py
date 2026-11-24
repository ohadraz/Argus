"""The schema job: Argus's schema, applied to the database `Settings` names.

`python -m apps.schema`, which `nox -s schema` and the e2e stack's bring-up
both run. What applying is - the chain run to its head, from wherever the
database is - is `postgres.apply_schema`'s; this is the process around it.

Applying destroys nothing unless asked to, and asking is not enough on its
own. `--destroy` drops the schema before applying it (`postgres.reset_schema`),
which is how a development stack is applied while `001` is still edited in
place - and it is refused unless the environment says it may be destroyed
(`Settings.schema_may_be_destroyed`). The flag says what is intended; the
setting says the database is one nobody minds losing. A deployment that keeps
its data sets neither, and runs the default.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from typing import Final

import psycopg
from core import DatabaseSettings, Settings, get_settings, the_clock
from postgres import apply_schema, connect, reset_schema

logger = logging.getLogger(__name__)

type ApplySchema = Callable[[psycopg.Connection], None]


class DestructionRefused(Exception):
    """What the job raises when told to destroy a schema the environment does
    not say may be destroyed."""


def the_schema_applied(conn: psycopg.Connection,
                       *,
                       destroy: bool,
                       settings: Settings,
                       apply: ApplySchema = apply_schema,
                       reset: ApplySchema = reset_schema) -> None:
    """Applies the schema to `conn`'s database - dropping it first only where
    `destroy` asks and `settings` allow it.

    Refused before anything is asked of the database: a refusal that had
    applied the chain first would have done the one thing a database somebody
    minds losing can survive, and then said no to the rest - and a reader of
    the refusal could not tell which half happened.

    `apply` and `reset` are what applying and destroying are, handed in so the
    choice between them is asserted without a database behind it.
    """
    if not destroy:
        apply(conn)
        return

    if not settings.schema_may_be_destroyed:
        raise DestructionRefused(
            f"`--destroy` drops every table and every row, and this environment does "
            f"not say its schema may be destroyed - set {_THE_SETTING}=true where it "
            f"may, which is a development stack's alone"
        )

    reset(conn)


def main(argv: Sequence[str] | None = None) -> None:
    """The job: the schema, applied to the database `Settings` names.

    A module entry point rather than a nox session's body, because the same act
    is wanted from three places that are not all nox - a local checkout, the e2e
    stack, and whatever brings this up the day the services are containerized.
    `nox -s schema` calls this; it does not reimplement it.

    `argv` is the command line, read from the process's own where not handed
    one.

    Says which database it applied to, and how, and not how it reached it: the
    URL carries a password, and a job whose ordinary output is a credential is a
    job whose output nobody can paste into an issue.

    The one `main` that configures logging for itself. Every other process's
    logging is set up by `telemetry` as its telemetry starts, and this job
    starts none: it runs once, before anything there is to trace.
    """

    the_clock()
    logging.basicConfig(level=logging.INFO)

    asked = _the_command_line().parse_args(argv)
    settings = get_settings()

    with connect(DatabaseSettings.of(settings)) as conn:
        the_schema_applied(conn, destroy=asked.destroy, settings=settings)
        logger.info("schema %s to %s on %s:%s",
                    "dropped and applied" if asked.destroy else "applied",
                    conn.info.dbname, conn.info.host, conn.info.port)


def _the_command_line() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m apps.schema",
                                     description="Applies Argus's schema.")
    parser.add_argument(
        "--destroy", action="store_true",
        help=f"drop the schema, every row with it, before applying it - refused "
             f"unless {_THE_SETTING}=true"
    )

    return parser


# The environment variable that lets the job destroy, as `Settings` reads it.
_THE_SETTING: Final = "SCHEMA_MAY_BE_DESTROYED"


if __name__ == "__main__":
    main()
