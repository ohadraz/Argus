"""What a write tool's refusal says about the estate it leaves.

One rule for every action through the deployment platform, and it is where
knowledge stops: at a change request that went out and got no answer saying it
was not applied.

Before any change is asked for, the estate is as it was found, whatever the
platform said - a read changes nothing, so a refusal there says it left nothing.
At a change the platform answered it did not handle, what is left is what the
earlier calls answered for, and that is known to be all of it. At one whose
answer was lost, the earlier calls' changes are still carried, because they are
in place either way - and nothing is said to be all of it, and nothing is marked:
a platform marked unreachable narrows the walk onto other actions, judged against
a service that may be recovering from this one.

Which of the platform's failures said the request was not applied is the
adapter's to tell (`known_not_applied`); where in the action a failure fell is
the action's, which is why each says `asked_to_change` itself.
"""

from __future__ import annotations

from argus_core.mcp_transport import (
    a_refusal_saying_what_it_left,
    an_unreachable_platform,
    with_what_it_left,
)
from argus_core.models import DEPLOYMENT_PLATFORM, UndoDescriptor
from deployment_platform import DeploymentPlatformError, PlatformUnreachable


def a_platform_refusal(said: str,
                       error: DeploymentPlatformError,
                       *,
                       asked_to_change: bool,
                       left_behind: UndoDescriptor | None = None) -> str:
    """`said`, marked for what the failure leaves known about the estate.

    `asked_to_change` is whether the call that failed was a change request
    rather than a read; `left_behind` is what the calls before it changed, as
    they answered for it.

    The mark is what lets a caller tell every action through the platform
    being unavailable from this one being refused, and a refusal that changed
    nothing from one nobody can account for, without reading the words of any
    of them. Applied here rather than by the platform: what a response means is
    the platform's to say, and what to raise about it is the action's own.
    """
    if asked_to_change and not error.known_not_applied:
        return with_what_it_left(said, left_behind)

    if isinstance(error, PlatformUnreachable):
        return an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)

    return a_refusal_saying_what_it_left(said, left_behind)
