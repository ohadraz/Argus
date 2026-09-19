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

The set is declared here as a literal rather than derived from the registered
strategies. A strategy answers "what should be done about this cause"; this
answers "may Argus do that unasked", and deriving the second from the first
would let an action acquire autonomy by being implemented. Adding a kind is a
line somebody writes and defends.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from typing import Final

from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    Action,
    ActionType,
)

__all__ = [
    "GENERIC_MITIGATIONS",
    "AdmittedMitigations",
    "is_a_generic_mitigation"
]

# The kinds of action that may be taken without a human. Small enough to read
# in one sitting, which is the property that makes it reviewable at all.
type AdmittedMitigations = AbstractSet[ActionType]

GENERIC_MITIGATIONS: Final[AdmittedMitigations] = frozenset(
    {REVERT_FEATURE_FLAG, RESTART_SERVICE}
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
