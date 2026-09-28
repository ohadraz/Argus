"""Which actions Argus may take on its own authority (spec §13).

The question the Orchestrator's gate asks before anything mutating is called,
and the whole of what stands between a proposal and production.

It asks about membership of a closed set, not about whether the action can be
undone. That is the criterion both industry frames actually use: Google SRE's
*generic mitigations* are a defined, small set - drain, roll back, restart, add
capacity - applied before the cause is known, and ITIL's *standard change* is
pre-authorised for being routine and well understood rather than for being
reversible. Both decide on membership.

Argus's own rule used to be reversibility, and it fitted for as long as
reverting a flag was the only mitigation built. The two part company at the
first mitigation that changes no persistent state: a restart can be undone by
nothing, so "must be undoable" would put the industry's most common first
response behind a human gate while flipping a production flag stayed automatic -
backwards on any reading of blast radius. The undo descriptor goes back to being
what it always was: how a refuted mitigation is put back, not what admits it.

Adding capacity is the member that shows the criterion is what it says it is. It
restores nothing - what it leaves behind is a deployment larger than the one
anybody declared - and it is admitted on the same ground the other three are,
that it is a routine, well-understood procedure applied before the cause is
understood. A set that asked what an action puts back would have had to argue
about this one, and the argument would have been about the wrong thing.

The set is declared here as a literal rather than derived from the registered
strategies. A strategy answers "what should be done about this cause"; this
answers "may Argus do that unasked", and deriving the second from the first
would let an action acquire autonomy by being implemented. Adding a kind is a
line somebody writes and defends.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import Final

from argus_core.models import (
    PIN_AUTOSCALER,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    Action,
    ActionType,
    ServiceDependency,
    the_service_addressed_by,
)

__all__ = [
    "GENERIC_MITIGATIONS",
    "AdmittedMitigations",
    "is_a_generic_mitigation",
    "is_within_reach"
]

# The kinds of action that may be taken without a human. Small enough to read
# in one sitting, which is the property that makes it reviewable at all.
type AdmittedMitigations = AbstractSet[ActionType]

GENERIC_MITIGATIONS: Final[AdmittedMitigations] = frozenset(
    {
        REVERT_FEATURE_FLAG,
        RESTART_SERVICE,
        ROLL_BACK_DEPLOYMENT,
        SCALE_OUT,
        PIN_AUTOSCALER
    }
)


def is_a_generic_mitigation(action: Action,
                            admitted: AdmittedMitigations = GENERIC_MITIGATIONS) -> bool:
    """Whether Argus may take this action on its own authority (spec §13).

    A question about the kind, never about the instance. Absence from the set
    is a refusal rather than a default to permitted: a kind nobody has declared
    is one nobody has argued for, and assuming the best about it is how an
    unreviewed action reaches production the day it is implemented.
    """
    return action.action_type in admitted


def is_within_reach(action: Action,
                    alerting_service: str,
                    dependencies: Sequence[ServiceDependency]) -> bool:
    """Whether the thing this action is addressed to is within the estate Argus
    may touch.

    The second question, and the one the kind cannot answer. Until a mitigation
    could be aimed somewhere other than the service that was paged, there was
    nothing here to ask: the subject came from the alert, so the subject was by
    construction something Argus was already acting on. An address that comes
    from an investigation is different - a model can write a third party's name
    in it, a service in another part of the estate, or prose it mistook for a
    hostname - and no fact about the kind of action rules any of those out.

    Kept beside `is_a_generic_mitigation` rather than folded into it, because the
    two fail for different reasons and a reader picking the incident up needs to
    know which. "Argus does not do that" and "Argus does not touch that" are
    different sentences, and one of them is a reason to widen a declared set
    while the other is a reason to correct a register.

    Within reach is the alerting service itself, always - Argus has been
    restarting and rolling that one back since before there was a register, and
    making it conditional on a document somebody maintains would let a stale
    entry withdraw an authority nobody meant to withdraw. Otherwise it is a
    dependency the register lists for that service *and* marks as the
    organisation's own.

    Everything else is refused, and the refusal is the restrictive direction on
    purpose: an estate is not a thing to guess at, because something somewhere
    answers to almost any plausible service name. That includes an ownership
    nothing here recognises - `ServiceDependency.is_ours` tests for the one word
    that means ours, so a register that grows a fourth answer withholds authority
    rather than granting it.

    The dependencies arrive as a value, retrieved before the walk reached this
    question. That is the same discipline `propose_action` keeps about flag
    changes and for the same reason: whether Argus may act cannot depend on a
    document store being reachable at the moment it asks, and an empty list is
    what an unreachable register looks like - which leaves every mitigation
    addressed to the alerting service exactly as available as it was.
    """
    addressed_to = the_service_addressed_by(action)

    if addressed_to is None or addressed_to == alerting_service:
        return True

    return any(
        dependency.name == addressed_to and dependency.is_ours
        for dependency in dependencies
    )
