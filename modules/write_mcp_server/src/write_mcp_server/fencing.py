"""Making a change only for the claim that holds the run it is made for.

A worker paused past its lease wakes holding a claim its run has moved past,
and its next change to the world would be a second walk acting on an incident
somebody else is walking. The database refuses that worker's writes
(`core.fencing`); this refuses its changes. A call that changes anything
says which claim it is made for, the run is asked whether that claim still holds
it, and the run is kept so until the change is made - checked and let go, it
could be taken back between the answer and the change.

What a refusal means decides how it is said. A claim the run has moved past is
a lost run, marked so the walk stops. A call naming no claim, or one whose run
could not be asked after, is refused as an ordinary refusal: neither says the
run was lost, and a walk told it was would stop in silence where it should reach
a human. So is a change registered as marked whose call names no action: its
write could not say whose it was. All are refused before the tool runs, and say
they left nothing. A change whose run has another change already being made for
it is refused too, before it runs - but without saying it left nothing, since
the change asking is that same one asked again, and the first may have landed.

Reads are answered as they always were. Nothing a read does can be got wrong by
a second walk.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager, suppress
from typing import Any, Final

from core import DatabaseSettings, Fence
from incident_record.repository import runs
from mcp.types import AnyFunction, ContentBlock
from mcp_transport import (
    FENCE_META_KEY,
    TracedFastMCP,
    a_lost_run,
    a_refusal_saying_what_it_left,
)
from postgres import connect

from write_mcp_server.marking import the_action_in

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
# a server that hung holding a run, not a wait anybody expects: the database
# closes the connection, and the run is let go with it.
LONGER_THAN_ANY_CHANGE: Final = "15min"

# How long a change waits for its run to be free before it is refused as one
# already being made. Above the moment a claim holds the run for while it
# commits, which is what an honest wait is for; below a restart, the one change
# that can outlast the client's wait for its answer - so a restart asked again,
# over a connection that gave out while the first was still being made, is
# refused rather than made twice. Every other change is usually over within this wait,
# so one asked again is waited out and asked again: that redo is crash-resume's
# to answer, not this.
LONGER_THAN_ANY_CLAIM: Final = "5s"


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
        self._marked: set[str] = set()

    @property
    def changes(self) -> frozenset[str]:
        """Every tool registered as a change, by name."""
        return frozenset(self._changes)

    @property
    def marked(self) -> frozenset[str]:
        """Every change whose writes carry the mark of the action they are made
        for, by name."""
        return frozenset(self._marked)

    def change(self, marked: bool = False) -> Callable[[AnyFunction], AnyFunction]:
        """Registers a tool, as `tool()` does, as one that changes the world -
        and, `marked`, as one made only for a call naming the action it is for."""
        register = self.tool()

        def registered(tool: AnyFunction) -> AnyFunction:
            self._changes.add(tool.__name__)

            if marked:
                self._marked.add(tool.__name__)

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

        # Both refused before the tool runs, so both say they left nothing: a
        # refusal that said less would be written up as nobody knowing whether
        # anything was changed.
        if held is None:
            raise RuntimeError(a_refusal_saying_what_it_left(
                f"[{name}] changes the world, and the call named no run to change it for"
            ))

        # Before the hold is asked for, as the fence is: a write nobody could
        # tell from a person's is not made, and the run is not kept still for it.
        if name in self._marked and the_action_in(meta) is None:
            raise RuntimeError(a_refusal_saying_what_it_left(
                f"[{name}] marks what it writes with the action it is made for, and "
                f"the call named none"
            ))

        held_for_now = ExitStack()

        try:
            still_held = held_for_now.enter_context(self._hold_for_a_change(held))
        except runs.ChangeInFlight as in_flight:
            # Refused without saying it left nothing, unlike the refusals
            # around it: what asks is this change asked again while the first
            # is still being made, and that one may well have changed the world.
            # The walk records what it left as unknown, and a person is told.
            raise RuntimeError(
                f"[{name}] was not made for run [{held.run_id}]: {in_flight}"
            ) from in_flight
        except Exception as unasked:
            raise RuntimeError(a_refusal_saying_what_it_left(
                f"whether run [{held.run_id}] is still held for [{name}] could not be "
                f"asked: {unasked}"
            )) from unasked

        with _let_go_after(held_for_now, name):
            if not still_held:
                raise RuntimeError(a_lost_run(
                    f"[{name}] was asked for by claim [{held.epoch}] of run "
                    f"[{held.run_id}], which the run has moved past"
                ))

            return await super().answer(name, arguments, meta)


@contextmanager
def holds_in_the_database(settings: DatabaseSettings,
                          wait: str = LONGER_THAN_ANY_CLAIM,
                          idle: str = LONGER_THAN_ANY_CHANGE) -> Generator[HoldForAChange]:
    """The run asked after and kept on a connection of the change's own.

    Kept by the session rather than by a transaction (`runs.hold_for_a_change`),
    so the connection commits each statement as it is said and holds nothing
    the event log would wait behind. The database closes it if nothing is said
    on it for `idle`, which lets the run go, and a run already held is waited
    for no longer than `wait` - both said as Postgres says a duration, and
    both the tier's own bounds unless a caller has reason to say shorter ones.

    One connection per change rather than a pool, because closing it is the
    one way of letting go that cannot fail to: a pooled connection whose
    letting go had failed would carry the run, held, into whichever change
    took it next. A change is rare and slow, and a connection costs it nothing
    worth counting.
    """
    @contextmanager
    def hold(held: Fence) -> Generator[bool]:
        with (
            connect(settings, connection={
                "autocommit": True,
                "options": f"-c idle_session_timeout={idle} -c lock_timeout={wait}"
            }) as conn,
            runs.hold_for_a_change(conn, held) as still_held
        ):
            yield still_held

    yield hold


def _the_claim_in(meta: Mapping[str, Any] | None) -> Fence | None:
    """The claim a call says it is made for, or `None` where it says none."""
    spoken = (meta or {}).get(FENCE_META_KEY)

    return Fence.heard(spoken) if isinstance(spoken, str) else None


@contextmanager
def _let_go_after(held_for_now: ExitStack, tool: str) -> Generator[None]:
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
