"""The schema job: Argus's schema, applied to the database `Settings` names.

`python -m apps.schema`, which `nox -s schema` and the e2e stack's bring-up
both run. What applying is - the drop, then the chain to head - is
`postgres.reset_schema`'s; this is the process around it.
"""

from __future__ import annotations

import logging

from core import DatabaseSettings, get_settings
from postgres import connect, reset_schema

logger = logging.getLogger(__name__)


def main() -> None:
    """The job: the schema, applied to the database `Settings` names.

    A module entry point rather than a nox session's body, because the same act
    is wanted from three places that are not all nox - a local checkout, the e2e
    stack, and whatever brings this up the day the services are containerized.
    `nox -s schema` calls this; it does not reimplement it.

    Says which database it applied to, and not how it reached it: the URL
    carries a password, and a job whose ordinary output is a credential is a job
    whose output nobody can paste into an issue.

    The one `main` that configures logging for itself. Every other process's
    logging is set up by `telemetry` as its telemetry starts, and this job
    starts none: it runs once, before anything there is to trace.
    """
    logging.basicConfig(level=logging.INFO)

    with connect(DatabaseSettings.of(get_settings())) as conn:
        reset_schema(conn)
        logger.info("schema applied to %s on %s:%s",
                    conn.info.dbname, conn.info.host, conn.info.port)


if __name__ == "__main__":
    main()
