"""Setting a feature flag's state in the provider (spec §7.3, §12.1).

The write tier's one act on the flag provider. How the provider is reached, under
which credential, and how long it takes to show a change are the provider's
adapter's, behind `FlagProviderWrites`; what is left here is the tier's part: the
change asked of the provider is the one the caller asked for, what comes back is
the undo the provider's write produced, and a failure reaches the caller as a
refusal saying what it left - nothing, something it cannot vouch for, or the undo
that puts the flag back.

One function serves both directions, because a flag causes an incident by
changing and the damaging direction is not always "on" - a flag switched off can
disable a fallback, or withdraw the very mitigation someone applied an hour ago.
Undoing such a change means switching the flag back on, and an agent that could
only clear flags could not mitigate that incident at all. It is also what makes
undoing a *mitigation* the same call with the state reversed.
"""

from __future__ import annotations

import logging

from core.mcp_transport import a_refusal_saying_what_it_left
from core.models import FlagUndo
from flag_provider import FlagProviderWrites, FlagWriteFailed

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


def set_flag(flag: str, enabled: bool, flags: FlagProviderWrites) -> FlagUndo:
    """Sets `flag` on or off through the provider and returns the undo its
    write produced.

    The provider returns only once the change is visible to evaluation, so a
    caller about to judge whether the service recovered judges a service that
    was actually changed.

    Raises `FlagNotSet` where the provider did not do it - saying, as every
    write tool's refusal says, what it left behind. A write the provider never
    took left nothing; one whose answer was lost may have flipped the flag, and
    says nothing either way. One the provider took and nobody saw evaluating has
    flipped it, so the refusal carries what puts it back: recorded nowhere else,
    it is a flag no withdrawal would ever touch.
    """
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
