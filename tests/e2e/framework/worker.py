"""The stack's worker as a case holds it: paused, so that nothing walks an
incident until the case has done what has to come first, and resumed.

For a case whose order is the point. Nothing in Argus stands between an alert
and the Investigator's opening, so a person writing in the incident's thread
"before the walk" races the walk unless the walk is kept from starting. The
case stops the process rather than the walk: suspended, the worker claims
nothing, and everything else in the stack - the thread, the ingestion, the
intent agent - carries on without it.

Suspended as a tree. On Windows a venv's `python.exe` is a launcher whose child
is the interpreter, and suspending only the pid the stack started leaves the
worker running.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Final

import psutil

# Where the stack says the worker is. Kept in step with the noxfile's
# `_THE_WORKER_PID_VARIABLE` by hand, as the addresses in `framework.chat` are:
# the noxfile is read before anything is installed, and is imported by nothing.
WORKER_PID_VARIABLE: Final = "ARGUS_E2E_WORKER_PID"


def the_worker_is_paused() -> Callable[[], None]:
    """A `given` step: the worker claims nothing until `the_worker_resumes`.

    The suite's teardown resumes it whatever the verdict, so a case that fails
    while it is paused does not leave the next one with nobody to walk it.
    """
    def paused() -> None:
        for process in _the_worker():
            process.suspend()

    return paused


def the_worker_resumes() -> None:
    """Lets the worker go on. Harmless when it was never paused, which is what
    lets the suite's teardown call it after every case."""
    for process in _the_worker():
        process.resume()


def _the_worker() -> list[psutil.Process]:
    """The process the stack started as the worker, and everything under it."""
    started = psutil.Process(int(os.environ[WORKER_PID_VARIABLE]))

    return [started, *started.children(recursive=True)]
