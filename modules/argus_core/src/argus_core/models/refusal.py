"""Why an action was not taken, said as a value rather than as a sentence.

The tier gate refuses for two reasons, and they are not the same finding: an
investigation that produced nothing to act on has run out of ideas, where one
that produced an action nobody has pre-authorised ran into the boundary Argus is
built around. A reader following an incident needs to know which of those
happened, and so does anything counting how often the boundary is what stopped a
walk.

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

    # The investigation named a cause and no mitigation answers it. Not a
    # failure of the gate - there was never an action for it to judge.
    NO_MITIGATION_PROPOSED = "no-mitigation-proposed"
    # There is something to do and nobody has pre-authorised doing it. The one
    # refusal that is the autonomy boundary doing its job (spec §13): the set of
    # generic mitigations is closed, and a kind absent from it is one nobody has
    # argued for rather than one that happens not to be listed yet.
    NOT_A_GENERIC_MITIGATION = "not-a-generic-mitigation"
    # This has been done to this subject as often as the incident allows. The
    # control a repeatable mitigation actually needs: the failure mode of a
    # restart is repetition, not irreversibility, and a restart loop is what a
    # cap exists to stop.
    ALREADY_TRIED_ENOUGH = "already-tried-enough"
