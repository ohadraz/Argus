"""Keeping a walk whose run was taken back from acting as though it still held it.

A lease says when a worker may be presumed gone, and nothing stops a worker that
was only paused from carrying on once it wakes. Each claim of a run moves the
run's epoch on, so whatever that worker does after the run was taken back
carries an epoch the run no longer has - and what learns so says it here.
"""

from __future__ import annotations


class RunLost(Exception):
    """The run this process was walking is no longer its own.

    A newer claim holds it: the lease ran out while this process was paused,
    and another worker took the run back. Whatever this process does after
    learning so is a second walk of an incident somebody else is walking, so
    the one answer is to stop - nothing settled, nothing escalated, nothing put
    back.
    """
