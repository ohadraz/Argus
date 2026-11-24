"""Where a run of the walk is, as the queue holds it.

A contract rather than the queue's own type, because two parties spell it: the
queue that moves a run between states, and the schema's fence, which lets a
worker write only while its run is `running`. A word the fence spells in SQL
and the queue in Python is one that could drift apart unnoticed - so the schema
spells it from here.
"""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    """Where a run is, which is not where its incident is.

    An incident's status says what Argus knows about the failure; a run's state
    says whether anything is currently thinking about it. A queued run on a
    resolved incident is a bug, and it takes two columns to be able to see it.
    """

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
