"""Where a planned change finds the platform's sync switch, compared with its plan.

One rule for every action that suspends reconciliation before it changes live
state - the rollback, the scale-out and both pins - because the switch is one
switch, and four readings of it would come to say four things.

The plan recorded whether the platform was reconciling the application, and the
Application carries the mark of whatever last wrote the switch. Read together:

- found reconciling, still reconciling, under no mark of this claim's: the
  suspension is still to be written;
- found reconciling, off under this claim's mark: this claim suspended it, and
  the switch is where the change needs it;
- found off, still off: there was never anything to suspend;
- anything else is somebody's change since - a switch turned off under no mark of
  this claim's, one turned back on after this claim turned it off, or one turned
  on that the plan found off.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto

from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    Mark,
    MarkFound,
)


class Switch(Enum):
    """Where the sync switch stands for a change about to be written."""

    # Reconciling, as the plan found it: the change suspends it first.
    TO_SUSPEND = auto()
    # Already where the change needs it: off, by this claim or from before it.
    AS_NEEDED = auto()
    # Somebody else's switch since the plan.
    CHANGED_SINCE = auto()


def the_switch(was_syncing_itself: bool,
               syncing_now: bool,
               marked_by: MarkFound | None,
               claim: Mark | str) -> Switch:
    """Where the switch stands, given what the plan found (`was_syncing_itself`),
    what it reads now, and the mark the Application carries - compared with
    `claim`: the mark a write is made under, or the claim's id alone for a read
    that writes nothing."""
    this_claim_s = is_this_claim_s(marked_by, claim)

    if not was_syncing_itself:
        return Switch.CHANGED_SINCE if syncing_now else Switch.AS_NEEDED

    if syncing_now:
        return Switch.CHANGED_SINCE if this_claim_s else Switch.TO_SUSPEND

    return Switch.AS_NEEDED if this_claim_s else Switch.CHANGED_SINCE


def this_claim_s_suspension_stands(was_syncing_itself: bool,
                                   syncing_now: bool,
                                   marked_by: MarkFound | None,
                                   claim: Mark | str) -> bool:
    """Whether a suspension this claim wrote is in place now - which a refusal
    then carries, since only the plan says how to put it back."""
    return was_syncing_itself and not syncing_now and is_this_claim_s(marked_by, claim)


def is_this_claim_s(marked_by: MarkFound | None, claim: Mark | str) -> bool:
    """Whether the mark found on an object names `claim` - a write's mark, or a
    read's claim by its id. The moment a mark says it was written plays no part:
    whose a change is does not wait on when."""
    action_id = claim.action_id if isinstance(claim, Mark) else claim

    return marked_by is not None and marked_by.action_id == action_id


def suspend_where_it_is_to_be(application: str,
                              switch: Switch,
                              platform: DeploymentPlatformWrites,
                              mark: Mark,
                              refusing: Callable[[str, DeploymentPlatformError], Exception]
                              ) -> None:
    """The suspension, carrying `mark`, where `switch` says it is still to be
    written - and the action's own refusal (`refusing`, handed what to say and the
    platform's failure) where the platform will not take it.

    Apart from the reads before it, because this is the first change an action
    asks for: a failure here may have suspended the sync, where a read cannot.
    """
    if switch is not Switch.TO_SUSPEND:
        return

    try:
        platform.suspend_sync(application, mark)
    except DeploymentPlatformError as error:
        raise refusing(
            f"could not suspend the sync of [{application}]: {error}", error
        ) from error
