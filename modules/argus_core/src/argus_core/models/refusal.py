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

    # There was a mitigation for this cause and it could not say what to act
    # on - a flag the provider never recorded moving, a window naming two
    # changes and no way to choose. Not a failure of the gate: there was never
    # an action for it to judge, and what is missing is evidence.
    NO_MITIGATION_PROPOSED = "no-mitigation-proposed"
    # The cause is known and nothing in the closed set answers it at all. The
    # other silence that reaches the gate with no action, and a different thing
    # to say to whoever picks the incident up: not "work out what to do" but
    # "this is not ours to do anything about". An upstream dependency's outage
    # is the case it was named for.
    NOTHING_ANSWERS_THIS_MODE = "nothing-answers-this-mode"
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
