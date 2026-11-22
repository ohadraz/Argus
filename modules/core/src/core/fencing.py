"""Keeping a walk whose run was taken back from acting as though it still held it.

A lease says when a worker may be presumed gone, and nothing stops a worker that
was only paused from carrying on once it wakes. Each claim of a run moves the
run's epoch on, so whatever that worker does after the run was taken back
carries an epoch the run no longer has - and what learns so says it here.

The database is what learns it. A worker's connection says which run and epoch
it writes for - its fence - and every table but the run's own refuses a write
whose run has since moved on, share-locking the run's row for the rest of the
transaction, so the run cannot be taken back under a write still being made. A
worker's connection that names no run is refused too: a walk writing for no run
is a worker that forgot to fence, and a fence nobody is made to put up is one a
stale walk gets round. Anything else - the web process, the relay, the schema
job - walks no run, and writes as it always did.

What a claim is and what holds one are the kernel's, here; saying one on a
connection is the database's, in `postgres.fencing`.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final


class RunLost(Exception):
    """The run this process was walking is no longer its own.

    A newer claim holds it: the lease ran out while this process was paused,
    and another worker took the run back. Whatever this process does after
    learning so is a second walk of an incident somebody else is walking, so
    the one answer is to stop - nothing settled, nothing escalated, nothing put
    back.
    """


@dataclass(frozen=True)
class Fence:
    """Which claim of which run a connection writes for, or a call to the
    write tier changes the world for."""

    run_id: str
    epoch: int

    def spoken(self) -> str:
        """This claim as it is said to another party: `<run id>:<epoch>`.

        Said on a worker's connections and in its calls to the write tier, and
        heard back by the database and by the tier - so one spelling, here.
        """
        return f"{self.run_id}:{self.epoch}"

    @staticmethod
    def heard(spoken: str) -> Fence | None:
        """The claim `spoken` names, or `None` where it names none.

        `None` rather than raised, because what is heard is whatever a caller
        sent, and a caller that sent something else named no run - which is the
        hearer's to refuse, not a run to be made up for it.
        """
        run_id, _, epoch = spoken.rpartition(":")

        # ASCII digits alone: they are what `spoken` writes and the database
        # reads, and `isdigit` alone passes a "²" that `int` then refuses.
        if not run_id or not (epoch.isascii() and epoch.isdigit()):
            return None

        return Fence(run_id=run_id, epoch=int(epoch))


class Holding:
    """The run this process is walking, as the claim it holds - or none, between
    runs.

    One per process rather than per thread: a walk is one run at a time, and its
    writes are made from threads it never sees - a checkpoint LangGraph saves in
    the background is as much the run's as a node's own.
    """

    def __init__(self) -> None:
        self._held: Fence | None = None
        self._acting_for: str | None = None

    def current(self) -> Fence | None:
        """The claim held now, or `None`."""
        return self._held

    @contextmanager
    def of(self, held: Fence) -> Generator[None]:
        """`held` for as long as the block runs, and nothing after - however it
        ends."""
        self._held = held

        try:
            yield
        finally:
            self._held = None

    def current_action(self) -> str | None:
        """The action a change is being made for now, by its row's id, or `None`."""
        return self._acting_for

    @contextmanager
    def acting_for(self, action_id: str) -> Generator[None]:
        """`action_id` as the action changes are made for while the block runs,
        and none after - however it ends.

        Beside the run rather than inside it: a walk holds its run throughout,
        and takes one action at a time within it. The write tier marks what it
        writes with this, so that whoever reads the platform afterwards can tell
        which action a change was.
        """
        self._acting_for = action_id

        try:
            yield
        finally:
            self._acting_for = None


def was_lost(error: BaseException) -> bool:
    """Whether `error` says the run was lost, wherever it was said.

    Said by the walk as `RunLost`, or by the database as a refused write - and
    either may reach the caller inside something else that was raised while
    handling it, so the chain is followed to its end.

    The database's refusal is known by its SQLSTATE, read off whatever raised
    it: the kernel names no driver, and the state is the database's own word,
    whichever driver carried it.
    """
    seen: set[int] = set()
    reached: BaseException | None = error

    while reached is not None and id(reached) not in seen:
        seen.add(id(reached))

        if isinstance(reached, RunLost) or getattr(reached, "sqlstate", None) == _RUN_LOST:
            return True

        reached = reached.__cause__ or reached.__context__

    return False


# The SQLSTATE a write is refused with when the run it was made for is another
# claim's now. Our own, in a class Postgres leaves unused; `AR002`, a worker
# writing for no run, is a bug rather than a lost run and is not answered here.
_RUN_LOST: Final = "AR001"
