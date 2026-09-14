"""Why an action was not taken, said as a value rather than as a sentence.

The tier gate refuses for two reasons, and they are not the same finding: an
investigation that produced nothing to act on has run out of ideas, where one
that produced something irreversible ran into the boundary Argus is built
around. A reader following an incident needs to know which of those happened,
and so does anything counting how often the boundary is what stopped a walk.

Here rather than beside the gate, for the reason `Verdict` is here: the gate
names it, the published event carries it, and a vocabulary kept inside one of
those is one the other reads by comparing spellings.
"""

from __future__ import annotations

from enum import StrEnum


class Refusal(StrEnum):
    """What stopped a proposed action at the gate.

    The prose a reader sees is derived from this rather than stored beside it.
    Two sentences that must agree with one value is one of them eventually
    disagreeing.
    """

    # The investigation named a cause and nothing reversible answers it. Not a
    # failure of the gate - there was never an action for it to judge.
    NO_REVERSIBLE_ACTION = "no-reversible-action"
    # There is something to do and no way back from it. The one refusal that is
    # the autonomy boundary doing its job (spec §13), and the reason an action
    # without an undo descriptor never reaches production.
    NOT_REVERSIBLE = "not-reversible"
