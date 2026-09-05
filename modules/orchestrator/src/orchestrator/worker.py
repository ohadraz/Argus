from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from datetime import timedelta
from os import getpid

import psycopg
from argus_core.config import get_settings
from argus_core.db import connect

from orchestrator.entrypoint import run_incident
from orchestrator.repository import runs

"""The process that walks incidents.

It does one thing in a loop: take a run, walk it, settle it. Everything that
makes an investigation slow - the model, the retrieval, the wait for a service
to recover - happens here, in a process nobody is holding a connection open to.

A worker takes work rather than being given it, which is what makes a second
one harmless and a restart uneventful: the queue is the only coordination, and
a run whose worker stopped is simply the oldest thing nobody holds a lease on.
"""

logger = logging.getLogger(__name__)

# How a walk is performed. Injected so that what this module does with a run -
# claim it, renew while it walks, settle it either way - can be tested without
# a graph, a model or an MCP server behind it.
type Walk = Callable[[str], None]


def take_one_run(conn: psycopg.Connection,
                 claimed_by: str,
                 lease: timedelta,
                 walk: Walk = run_incident) -> bool:
    """Takes one run if there is one, walks it, and says whether it found any.

    Answers `False` for an empty queue rather than blocking on it, so the
    waiting is the caller's to decide - a loop that sleeps, a test that does
    not.

    A walk that raises settles the run as failed and does not re-raise: one
    incident Argus could not finish must not stop it working on the next, and
    the failure is recorded where the incident can be read beside it.
    """
    claimed = runs.claim(conn, claimed_by, lease)

    if claimed is None:
        return False

    try:
        walk(claimed.incident_id)
    except Exception as failure:
        logger.exception("run %s for incident %s failed",
                         claimed.id, claimed.incident_id)
        runs.fail(conn, claimed.id, f"{type(failure).__name__}: {failure}")
    else:
        runs.finish(conn, claimed.id)

    return True


def work_forever(walk: Walk = run_incident) -> None:
    """Takes runs for as long as the process lives.

    Looks again immediately after taking work and waits only when it found
    none: the interval is the delay a queued incident pays before anything
    starts on it, and paying it between two waiting runs would add it to an
    incident that was already in line.
    """
    settings = get_settings()
    lease = timedelta(seconds=settings.run_lease_seconds)
    idle_wait = settings.run_poll_interval_seconds
    me = this_worker()

    logger.info("worker %s waiting for runs", me)

    with connect() as conn:
        while True:
            if not take_one_run(conn, me, lease, walk):
                time.sleep(idle_wait)


def main() -> None:
    """The process itself: logging on, then take runs until killed.

    A `main` rather than bare module-level code, so that importing this module -
    which the tests do - starts nothing.
    """
    logging.basicConfig(level=logging.INFO)
    work_forever()


def this_worker() -> str:
    """Who a claim is held by, in a form a person reading the table can act on.

    The host and the process, because the question asked of a stuck run is
    always "is that still running, and where" - and a random id answers neither
    half of it.
    """
    return f"{socket.gethostname()}/{getpid()}"


if __name__ == "__main__":
    main()
