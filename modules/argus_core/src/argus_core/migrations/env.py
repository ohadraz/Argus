"""How Alembic reaches Argus's database.

Run by Alembic rather than imported by anything, which is why it is a script
with its work at the bottom instead of a module with an entry point.

The URL comes from `Settings` and not from `alembic.ini`, so that the job, the
suites and a person typing `alembic upgrade head` all reach the same database
the application reaches - a connection string kept in two places is a job that
migrates something nothing else is looking at.

No `target_metadata`: Argus declares its tables in SQL rather than in SQLAlchemy
models, so there is nothing for `--autogenerate` to compare against. A revision
here is written, not generated.
"""

from __future__ import annotations

from alembic import context
from argus_core.config import get_settings
from sqlalchemy import create_engine, pool

# SQLAlchemy picks a driver from the URL's scheme and `postgresql` alone means
# psycopg2, which this workspace does not install. The application's own URL is
# the plain scheme because psycopg reads it directly, so the driver is named
# here rather than carried in `Settings` for one consumer's benefit.
_PLAIN_SCHEME = "postgresql://"
_WITH_THE_DRIVER = "postgresql+psycopg://"


def _the_database_url() -> str:
    """The application's database, said the way SQLAlchemy needs it said."""
    return get_settings().database_url.replace(_PLAIN_SCHEME, _WITH_THE_DRIVER, 1)


def run_migrations_offline() -> None:
    """Emits the SQL instead of running it, for `alembic upgrade --sql`.

    Nothing in Argus uses this; it is what lets somebody read what a revision
    would do to a database they are not willing to let it touch.
    """
    context.configure(url=_the_database_url(), literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Applies the chain against a real connection.

    A pool of its own, thrown away afterwards. The job runs once and exits, and
    a suite applies the schema between runs rather than during one, so nothing
    here is worth keeping a connection open for.
    """
    engine = create_engine(_the_database_url(), poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(connection=connection)

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
