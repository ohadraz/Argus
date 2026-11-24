"""Which step of an incident's walk the writes being made belong to.

A step's writes stand or fall with its checkpoint. A step that is run again -
after a crash, or after the model it asked was unavailable - first discards
what its interrupted attempt wrote, and it finds those rows by the step they
carry. So every row a step writes says which step wrote it, and the writers
read it from here rather than from an argument: the events a node publishes
pass through a publisher, an agent and a savepoint before they are written,
and a step threaded through every one of those is a step one of them forgets.

Bound by the walk around each node (`within_step`) and read by the
repositories that stamp it (`the_current_step`). Nothing outside a walk binds
one, so intake, a person's ending and the worker's own escalation write rows
that belong to no step - and are never discarded with one.

A context variable rather than a thread-local, so a step bound by one node
never leaks into another that happens to run on the same thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_THE_STEP: ContextVar[int | None] = ContextVar("argus_walk_step", default=None)


@contextmanager
def within_step(step: int) -> Iterator[None]:
    """Says, for as long as the block runs, that every write made in it is
    step `step`'s - and stops saying it however the block ends."""
    bound = _THE_STEP.set(step)

    try:
        yield
    finally:
        _THE_STEP.reset(bound)


def the_current_step() -> int | None:
    """The step the writes being made belong to, or `None` outside a walk's
    step."""
    return _THE_STEP.get()
