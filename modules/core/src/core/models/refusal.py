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

    # There was a mitigation for this cause and the evidence did not say what
    # to act on - a candidate naming nothing, a dependency nobody named, a
    # record nobody could read. Not a failure of the gate: there was never an
    # action for it to judge, and what is missing is evidence.
    NO_MITIGATION_PROPOSED = "no-mitigation-proposed"
    # The candidate named the change it blames, and the record of what changed
    # holds no such change - a flag the provider never recorded moving. Not the
    # silence above, though it too reaches the gate with no action: the
    # candidate said what to undo, and only the record could say which way to
    # put it back. Said as that silence, a write-up read it as Argus having no
    # mitigation for a flag and never told a person to switch the flag off.
    NAMED_CHANGE_NOT_RECORDED = "named-change-not-recorded"
    # The cause is known and the fault is in a service another company runs, which
    # nothing Argus may do reaches. A third silence that reaches the gate with
    # no action, and a different thing to say to whoever picks the incident up:
    # not "work out what to do" but "this is not ours to do anything about".
    SOMEBODY_ELSES_SERVICE = "somebody-elses-service"
    # The cause is known and an action reaches it - and taking that action would
    # undo a change somebody meant. A rollback of a deliberate rename brings the
    # monitoring's sight back by taking the rename away, and what is owed instead
    # is the monitoring brought up to the change. Not one refusal with the one
    # above, though both reach the gate with no action: said as "nothing Argus
    # can do", this one is false - there is something, and it was declined - and
    # a reader who believed it would write that Argus could not act.
    WOULD_UNDO_A_MEANT_CHANGE = "would-undo-a-meant-change"
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
    # Distinct from the three above it in where it leaves the walk. Each of those
    # rejects a particular action, so the next candidate is worth reaching for;
    # this rejects the possibility of confirming any action on this incident, and
    # a second candidate is no better placed than the first.
    NOTHING_COULD_CONFIRM_IT = "nothing-could-confirm-it"


# Why the gate refused, in the one sentence the timeline, a candidate's row and
# the review all say it in - three spellings of one reason read as three
# reasons. Each carries its own subject, so it reads after "Refused to act - ",
# as a row on its own, and as a review's reason, where no line before it lends
# a bare "it" or "the action" a meaning. The cap says "the action" alone: the
# review never shows it, and "would test" is wrong of a candidate that was.
_WHY_IT_WAS_REFUSED = {
    # Said as what was missing rather than as what did not happen. "No
    # mitigation was proposed" reads as Argus having none for the candidate,
    # and a reader who believed it would ask for one to be built.
    Refusal.NO_MITIGATION_PROPOSED: "nothing in the evidence said what to act on to test "
                                    "the candidate",
    # The person, because the next step is theirs: the candidate says what to
    # undo, and nothing Argus read says which way.
    Refusal.NAMED_CHANGE_NOT_RECORDED: "the change the candidate names is not in the record "
                                       "of what changed, so undoing it is left to a person",
    # Said as what it is rather than as an absence. These two are Argus having
    # understood the incident and taking nothing for it - a reader who took
    # either for a thin investigation would go looking for evidence instead of
    # for whoever can act. And each says its own reason, because the two send a
    # reader to different people: whoever can call the third party, or whoever
    # owns the monitoring that did not follow a change somebody meant. Said of
    # the second as "nothing Argus can do", it was false - a rollback reaches it
    # and was declined - and a model reading it wrote that Argus could not act.
    Refusal.SOMEBODY_ELSES_SERVICE: "the failure is in a service another company runs, "
                                    "and nothing Argus can do reaches it",
    Refusal.WOULD_UNDO_A_MEANT_CHANGE: "the only action that would test the candidate "
                                       "undoes a change that was made on purpose",
    # The kind, because the kind is what somebody widens.
    Refusal.NOT_A_GENERIC_MITIGATION: "the action that would test the candidate is not "
                                      "of a kind Argus may take unasked",
    # The cap, said as the count it is rather than as a failure. A reader who
    # took this for something going wrong would look for a fault; what happened
    # is a control working.
    Refusal.ALREADY_TRIED_ENOUGH: "the action has already been tried on this subject as "
                                  "often as the incident allows",
    # Said as the estate rather than as the action, because that is the half
    # somebody can correct. The kind was fine and the address was not, and a
    # reader who read this as "Argus may not do that" would go looking at the
    # declared set instead of at the service register.
    Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH: "the action that would test the candidate is "
                                          "addressed to a service outside the estate "
                                          "Argus may act on",
    # Said as what nobody could find out rather than as what Argus declined,
    # because the action is not what was wrong with it. A reader who took this
    # for Argus doubting the diagnosis would go looking for better evidence of
    # the cause; what is missing is evidence of the *outcome*, which no amount
    # of investigating supplies. The action still stands, and somebody has to
    # take it.
    Refusal.NOTHING_COULD_CONFIRM_IT: "nothing would say whether the action that would "
                                      "test the candidate worked inside the time Argus "
                                      "waits, so it is recommended rather than taken"
}


def why_it_was_refused(refusal: Refusal) -> str:
    """The sentence every reader says one refusal in.

    A subscript rather than a `get`, deliberately: a refusal nobody has written
    a sentence for raises - in the gate, before anything is tried - rather than
    reaching a reader as a blank they would take for nothing having happened.
    """
    return _WHY_IT_WAS_REFUSED[refusal]
