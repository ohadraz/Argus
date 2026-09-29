"""Why an action was not taken, said as a value rather than as a sentence.

The tier gate refuses for several reasons and they are not the same finding: an
investigation that produced nothing to act on has run out of ideas, one that
produced an action nobody has pre-authorised ran into the boundary Argus is built
around, and one that produced an admitted action aimed somewhere Argus may not
touch ran into a different boundary entirely. A reader following an incident needs
to know which of those happened, and so does anything counting how often a
boundary is what stopped a walk.

They are also not equally a reason to change anything. One asks for more
evidence, one asks whether a kind of action should be pre-authorised, one asks
whether a register entry is right, and one is a cap doing exactly its job.

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
    # There is something to do, its kind is pre-authorised, and the service it
    # is addressed to is not one Argus may touch. The only refusal that is about
    # the *instance* rather than the kind, and it exists because a mitigation
    # can now be aimed at a service the alert never named: an address that came
    # from an investigation can be a third party's, somewhere else in the estate,
    # or prose a model mistook for a hostname.
    #
    # Distinct from NOT_A_GENERIC_MITIGATION, and the distinction is what a
    # reader does next. That one says Argus does not do this kind of thing, and
    # is answered by somebody widening a declared set; this says Argus does not
    # touch that, and is usually answered by somebody correcting an entry in the
    # service register.
    OUTSIDE_WHAT_ARGUS_MAY_TOUCH = "outside-what-argus-may-touch"
    # There is something to do, its kind is pre-authorised, the subject is
    # Argus's to touch - and nothing could tell Argus afterwards whether it
    # worked. The only refusal that is about the *evidence after* the action
    # rather than about the action itself, and the only one that is not a
    # judgement on the proposal at all: the action may be exactly right, and
    # taking it would still be taking it blind.
    #
    # What makes it necessary is an incident found by something other than a
    # series. Every mitigation Argus takes is watched for in the minutes after
    # it, and where the only thing that would answer is a check somebody else
    # runs on a schedule of their own, those minutes carry nothing and the next
    # answer is days away. An action reported as taken and never judged is worse
    # than one not taken, because the incident looks handled.
    #
    # Distinct from the five above in where it leaves the walk. Each of those
    # rejects a particular action, so the next candidate is worth reaching for;
    # this rejects the possibility of confirming any action on this incident, and
    # a second candidate is no better placed than the first.
    NOTHING_COULD_CONFIRM_IT = "nothing-could-confirm-it"
