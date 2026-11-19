"""Planning a feature flag's change, and making it only where nobody has moved the
flag since the plan (spec §7.3, §12.1).

The write tier's one act on the flag provider, in two calls. The plan reads the
flag as the provider holds it - through the admin read, never the cached
evaluation - and dates the read by the provider's own clock, changing nothing.

The change is then made over the plan, and a flag's value cannot say whether it
still stands as planned: it is a bool, and two changes put it back where it was.
So the provider's history since the plan's read decides, read once and before
the write. How the provider is reached, under which credential, and how long it
takes to show a change are the provider's adapter's, behind
`FlagProviderWrites`; what is left here is the tier's part.

One function serves both directions, because a flag causes an incident by
changing and the damaging direction is not always "on" - a flag switched off can
disable a fallback, or withdraw the very mitigation someone applied an hour ago.
Undoing such a change means switching the flag back on, and an agent that could
only clear flags could not mitigate that incident at all. It is also what makes
undoing a *mitigation* the same call with the state reversed.
"""

from __future__ import annotations

import logging
from datetime import datetime

from core import parse_iso
from core.mcp_transport import (
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
)
from core.models import ChangeFound, FlagUndo, Made, NotMade, Planned
from flag_provider import FlagProviderUnavailable, FlagProviderWrites, FlagWriteFailed

logger = logging.getLogger(__name__)


class FlagNotSet(Exception):
    """The flag did not reach the requested state, whatever the reason.

    One exception for an unreachable provider, a rejected credential and a
    change that never became visible, because the caller's next move is the
    same for all three: the action did not happen, so nothing downstream may
    proceed as though it had. A change reported optimistically would have
    Mitigation confirm or refute a hypothesis against a service nothing was
    done to.
    """


def plan_flag(flag: str, enabled: bool, flags: FlagProviderWrites) -> Planned[FlagUndo]:
    """Plans setting `flag` on or off: the state the provider holds it in, which
    is what puts it back, dated by the provider's own time for the read.

    The state it is in rather than the opposite of the one asked for: a flag
    somebody already moved is planned from where it is. Nothing is written, so
    the descriptor names no environment and no time of a write.

    Raises `FlagNotSet` where the flag could not be read, saying it left
    nothing, and where it is already in the state asked for, as an exhausted
    action - refused rather than planned as a no-op, because a caller told it
    was done would record a mitigation that never happened, and the action
    spent is what lets the walk move on to another candidate.
    """
    try:
        state = flags.state_of(flag)
    except FlagProviderUnavailable as failure:
        raise FlagNotSet(a_refusal_saying_what_it_left(str(failure))) from failure

    if state.enabled == enabled:
        raise FlagNotSet(
            an_exhausted_action(f"flag [{flag}] is already {_state_name(enabled)}")
        )

    return Planned[FlagUndo](descriptor=FlagUndo(flag=flag, was_enabled=state.enabled),
                             since=state.read_at)


def set_flag(planned: Planned[FlagUndo], enabled: bool, flags: FlagProviderWrites) -> FlagUndo:
    """Sets the planned flag on or off through the provider, where nobody has
    changed it since the plan, and returns the undo its write produced.

    A state the plan found the flag in already is refused before anything is
    read or written: the plan refuses that change, and the write does not take
    it on the caller's word.

    The provider's history since the plan's read is read once, before the
    write - after it, the write would be its own evidence - and only the
    flag's own changes in it have a say:

    - none: the flag is as planned, and is written. The provider returns only
      once the change is visible to evaluation, so a caller about to judge
      whether the service recovered judges a service that was changed.
    - Argus's alone: the change asked again after its answer was lost. It
      landed, so it is answered as made and not written twice, dated by the
      first of them - the one that moved the flag off the plan, and what an
      undo later asks the history from.
    - anybody else's: a decision made since the plan, refused as changed since
      and not written over. Where Argus's own change landed among them, the
      refusal leaves the plan's undo behind, dated by the plan's read rather
      than by Argus's change: a put-back asks the history from that date, and
      must see a person's change made before Argus's to leave the flag as found.
      It says the change was performed, too: a flag has no suspension before
      its write, so the flip that landed is the change itself.
    - one nobody can attribute: it may be Argus's or somebody's, so it is
      neither - refused, nothing written.

    Raises `FlagNotSet` where the flag was not set - saying, as every write
    tool's refusal says, what it left behind. A history that could not be read
    left nothing. A write the provider never took left nothing; one whose answer
    was lost may have flipped the flag, and says nothing either way. One the
    provider took and nobody saw evaluating has flipped it, so the refusal
    carries what puts it back: recorded nowhere else, it is a flag no withdrawal
    would ever touch.
    """
    flag = planned.descriptor.flag

    if enabled == planned.descriptor.was_enabled:
        raise FlagNotSet(a_refusal_saying_what_it_left(
            f"flag [{flag}] was planned from {_state_name(enabled)}, so setting it "
            f"{_state_name(enabled)} would change nothing"
        ))

    made = _made_since_the_plan(planned, flags)

    if made is not None:
        logger.info("flag already set", extra={"flag": flag, "enabled": enabled})

        return made

    try:
        undo = flags.set(flag, enabled)
    except FlagWriteFailed as failure:
        said = str(failure)

        raise FlagNotSet(
            a_refusal_saying_what_it_left(said, failure.left_behind)
            if failure.known_not_applied or failure.left_behind is not None else said
        ) from failure

    logger.info("flag set", extra={"flag": flag, "enabled": enabled})

    return undo


def whether_it_was_made(planned: Planned[FlagUndo],
                        flags: FlagProviderWrites) -> Made[FlagUndo] | NotMade[FlagUndo]:
    """Whether the flip `planned` describes was made - the write's own rule on
    the plan, over the same one read of the provider's history since it, with
    the write left out, for a walk resumed after the worker that claimed it
    died.

    Argus's changes alone are the flip made: answered with what the write would
    answer, dated by the first of them - the one that moved the flag off the
    plan. No change to the flag is nothing landed, for the walk to make as the
    live walk would - leaving nothing behind, since a flag has no suspension
    before its write. Anything else is refused exactly as the write refuses it
    on the same history, since the two are one compare. Writes nothing.
    """
    made = _made_since_the_plan(planned, flags)

    if made is None:
        return NotMade[FlagUndo]()

    return Made[FlagUndo](descriptor=made, made_at=made.written_at)


def still_argus_s(planned: Planned[FlagUndo],
                  descriptor: FlagUndo,
                  flags: FlagProviderWrites) -> ChangeFound:
    """Whether the flip `descriptor` records, made from `planned`, is still as
    Argus left it - the write's own rule, read and not acted on, over one read
    of the provider's history since the plan's read, for a walk resumed after
    the worker that made it died.

    From the plan's `since`, as `set_flag` reads it, and not from the moment
    the descriptor says the change was written: the provider records the
    toggle before it answers, and the answer's date is whole seconds, so
    Argus's own change can fall before it.

    Only Argus's changes to the flag there, and it is still Argus's. Anybody
    else's is a decision made since, saying so. No change to the flag at all
    contradicts the row, which says Argus's flip landed - and so is a question
    nobody can answer, as are a change nobody can attribute and a history that
    could not be read. Writes nothing.
    """
    flag = descriptor.flag

    try:
        history = flags.changes_since(planned.since)
    except FlagProviderUnavailable as failure:
        logger.warning("still-argus-s check failed", exc_info=True, extra={"flag": flag})
        return ChangeFound(
            still_argus_s=None,
            found=f"could not read what changed to flag [{flag}] since it was planned: "
                  f"{failure}"
        )

    changes = [change for change in history if change.flag == flag]

    if any(change.made_by_argus is False for change in changes):
        return ChangeFound(
            still_argus_s=False,
            found=f"flag [{flag}] was changed by somebody else since it was planned"
        )

    if any(change.made_by_argus is None for change in changes):
        return ChangeFound(
            still_argus_s=None,
            found=f"flag [{flag}] was changed since it was planned, and nobody can say "
                  f"by whom"
        )

    if not changes:
        return ChangeFound(
            still_argus_s=None,
            found=f"the provider records no change to flag [{flag}] since it was planned, "
                  f"which contradicts the record that Argus's was made"
        )

    return ChangeFound(still_argus_s=True)


def _made_since_the_plan(planned: Planned[FlagUndo],
                         flags: FlagProviderWrites) -> FlagUndo | None:
    """What the provider's history since the plan's read says of the flip
    `planned` describes, raising as the write raises - the one compare the write
    and the claimed read share.

    Read once, and only the flag's own changes in it have a say: none is the
    flag as planned, answered `None`; Argus's alone are the flip already made,
    answered with the plan's undo dated by the first of them; anybody else's is
    changed since, refused - leaving the plan's undo behind, dated by the plan's
    read, where Argus's own change landed among them; one nobody can attribute
    is refused as a question nobody could answer. A history that could not be
    read left nothing.
    """
    flag = planned.descriptor.flag

    try:
        history = flags.changes_since(planned.since)
    except FlagProviderUnavailable as failure:
        raise FlagNotSet(a_refusal_saying_what_it_left(
            f"could not read what changed to flag [{flag}] since it was planned: {failure}"
        )) from failure

    changes = [change for change in history if change.flag == flag]
    first_of_argus = next((change for change in changes if change.made_by_argus is True), None)

    if any(change.made_by_argus is False for change in changes):
        raise FlagNotSet(a_change_made_since(
            f"flag [{flag}] was changed by somebody else since it was planned",
            None if first_of_argus is None else _dated(planned, planned.since),
            performed=first_of_argus is not None
        ))

    if any(change.made_by_argus is None for change in changes):
        raise FlagNotSet(a_refusal_saying_what_it_left(
            f"flag [{flag}] was changed since it was planned, and nobody can say by whom"
        ))

    if first_of_argus is None:
        return None

    return _dated(planned, parse_iso(first_of_argus.occurred_at))


def _dated(planned: Planned[FlagUndo], written_at: datetime) -> FlagUndo:
    """The plan's undo, dated `written_at` - the time a put-back later asks the
    provider's history from."""
    return planned.descriptor.model_copy(update={"written_at": written_at})


def _state_name(enabled: bool) -> str:
    return "on" if enabled else "off"
