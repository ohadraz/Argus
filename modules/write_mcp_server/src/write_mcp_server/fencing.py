"""Making a change only for the claim that holds the run it is made for.

A worker paused past its lease wakes holding a claim its run has moved past,
and its next change to the world would be a second walk acting on an incident
somebody else is walking. The database refuses that worker's writes
(`argus_core.fencing`); this refuses its changes. A call that changes anything
says which claim it is made for, the run is asked whether that claim still holds
it, and the run is kept so until the change is made - checked and let go, it
could be taken back between the answer and the change.

What a refusal means decides how it is said. A claim the run has moved past is
a lost run, marked so the walk stops. A call naming no claim, or one whose run
could not be asked after, is refused plainly: neither says the run was lost,
and a walk told it was would stop in silence where it should reach a human.

Reads are answered as they always were. Nothing a read does can be got wrong by
a second walk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager, suppress
from typing import Any, Final

from argus_core import DatabaseSettings, Fence, open_pool
from argus_core.mcp_transport import FENCE_META_KEY, TracedFastMCP, a_lost_run
from argus_incidents.repository import runs
from mcp.types import AnyFunction, ContentBlock

logger = logging.getLogger(__name__)

# Whether `fence` still holds its run, and the run kept so for as long as the
# block runs. A context manager, because keeping it is what makes the answer
# still true when the change is made.
type HoldForAChange = Callable[[Fence], AbstractContextManager[bool]]

# Where a process's holds come from, for as long as it serves: whatever they
# need opened is opened on the way in and closed on the way out.
type OpensHolds = Callable[[DatabaseSettings], AbstractContextManager[HoldForAChange]]

# How long the database lets a connection keep a run held with nothing said on
# it, which is how long a change may take. Above the longest the tier makes: a
# restart's two requests, then sixty looks a second apart, each up to the
# platform's ten-second timeout - eleven minutes and a little more. A bound on
# a server that hung holding a run, not a wait anybody expects.
LONGER_THAN_ANY_CHANGE: Final = "15min"


class FencedFastMCP(TracedFastMCP):
    """A traced server whose changes are made only for the claim holding their run.

    A tool is registered as a change with `change()` rather than `tool()`, and
    the difference is the whole of what this adds: a change is answered only
    once `hold_for_a_change` says the claim the call names still holds its run,
    and inside that hold. Asked inside the call's span, so a refusal is said in
    the trace of the walk it refused.
    """

    def __init__(self, name: str, hold_for_a_change: HoldForAChange, **settings: Any) -> None:
        super().__init__(name, **settings)
        self._hold_for_a_change = hold_for_a_change
        self._changes: set[str] = set()

    @property
    def changes(self) -> frozenset[str]:
        """Every tool registered as a change, by name."""
        return frozenset(self._changes)

    def change(self) -> Callable[[AnyFunction], AnyFunction]:
        """Registers a tool, as `tool()` does, as one that changes the world."""
        register = self.tool()

        def registered(tool: AnyFunction) -> AnyFunction:
            self._changes.add(tool.__name__)

            return register(tool)

        return registered

    async def answer(self,
                     name: str,
                     arguments: dict[str, Any],
                     meta: Mapping[str, Any] | None) -> Sequence[ContentBlock] | dict[str, Any]:
        """A change, made only for the claim holding its run; anything else, as
        it comes."""
        if name not in self._changes:
            return await super().answer(name, arguments, meta)

        held = _the_claim_in(meta)

        if held is None:
            raise RuntimeError(f"[{name}] changes the world, and the call named no run "
                               f"to change it for")

        held_for_now = ExitStack()

        try:
            still_held = held_for_now.enter_context(self._hold_for_a_change(held))
        except Exception as unasked:
            raise RuntimeError(f"whether run [{held.run_id}] is still held for [{name}] "
                               f"could not be asked: {unasked}") from unasked

        with _let_go_after(held_for_now, name):
            if not still_held:
                raise RuntimeError(a_lost_run(
                    f"[{name}] was asked for by claim [{held.epoch}] of run "
                    f"[{held.run_id}], which the run has moved past"
                ))

            return await super().answer(name, arguments, meta)


@contextmanager
def holds_in_the_database(settings: DatabaseSettings) -> Iterator[HoldForAChange]:
    """The run's own row, asked and kept on a pool of this process's own.

    Kept for the length of a transaction, which the database ends if nothing is
    said on it for `LONGER_THAN_ANY_CHANGE`. Committed once the change is made;
    a change that raised has it rolled back - either lets the run go.
    """
    with open_pool(settings, connection={
        "options": f"-c idle_in_transaction_session_timeout={LONGER_THAN_ANY_CHANGE}"
    }) as pool:
        @contextmanager
        def hold(held: Fence) -> Iterator[bool]:
            with pool.connection() as conn:
                yield runs.hold_for_a_change(conn, held)

        yield hold


def _the_claim_in(meta: Mapping[str, Any] | None) -> Fence | None:
    """The claim a call says it is made for, or `None` where it says none."""
    spoken = (meta or {}).get(FENCE_META_KEY)

    return Fence.heard(spoken) if isinstance(spoken, str) else None


@contextmanager
def _let_go_after(held_for_now: ExitStack, tool: str) -> Iterator[None]:
    """Lets the run go once the change is made, however it was made.

    A change that raised is raised as it was, the run let go on its way out. A
    change made and then not let go is answered all the same: the world was
    changed, and answering with a failure would have the walk record nothing to
    put back for a change that is there. Said, because a run kept past its
    change is a run nobody can take back until the database lets it go.
    """
    try:
        yield
    except BaseException as failed:
        # What the change raised is the answer, whatever letting go raises.
        with suppress(Exception):
            held_for_now.__exit__(type(failed), failed, failed.__traceback__)

        raise

    try:
        held_for_now.close()
    except Exception:
        logger.warning("the change was made and its run could not be let go",
                       exc_info=True, extra={"tool": tool})
