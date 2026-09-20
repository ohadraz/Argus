"""Performing the action the gate admitted, and recording what came of it."""

from __future__ import annotations

from functools import partial

from agent_mitigation import Verdict
from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    MitigationResumed,
    Publisher,
    VerdictReached,
    nobody,
    publish,
)
from argus_core.models import (
    Actor,
    IncidentStatus,
    UnreadVerdict,
    leaves_something_to_put_back,
    the_direction_of,
    the_subject_of,
)
from argus_incidents import IsStillWanted

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import (
    ActionAlreadyTaken,
    ChangeLanded,
    CompleteAction,
    RecordAction,
    RecordOutcome,
    TakeAction,
)
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    NEXT_CANDIDATE_ROUTE,
)
from orchestrator.walk.state import IncidentState


def mitigation_node(
    state: IncidentState,
    record_action: RecordAction,
    complete_action: CompleteAction,
    already_taken: ActionAlreadyTaken,
    record_outcome: RecordOutcome,
    still_wanted: IsStillWanted,
    take: TakeAction,
    change_landed: ChangeLanded,
    publisher: Publisher = nobody
) -> StateDelta:
    """Performs the action the gate admitted, and records what came of it
    (spec §7.3, §11.1).

    Reached only through the gate, so the action is known to exist and to carry
    a way back. The verdict it returns is the strongest evidence anything in
    this graph has - it was measured against re-queried metrics - and it is
    reported here rather than turned into a status, because turning it into one
    was how `refuted` came to mean two different things in two places.

    The row records the descriptor the *write tier returned* rather than the
    one proposed, since that is the account of what actually changed.
    """
    # Both, because an action is taken *for* a candidate: one without the other
    # is not an attempt this node can account for, and recording it would leave
    # a row nothing can attribute. The gate guarantees both are here; this says
    # so in a way the type checker can read.
    if state.proposed_action is None or state.hypothesis is None:
        return _nothing_to_act_on()

    # The claim goes in before anything happens, so that a walk resumed inside
    # this node is refused by the database rather than by a check it could race
    # with. Losing it means an earlier attempt already acted on this candidate.
    if not record_action(
        state.incident_id,
        hypothesis_id=state.hypothesis.id,
        action_type=state.proposed_action.action_type,
        # What the action acts on, not what the candidate calls the fault. The
        # row is the only account of what this attempt changed, and every
        # reader of it afterwards - the write-up, and the memory the next
        # incident is ordered by - has nowhere else to ask. A candidate's
        # subject is prose a model wrote about the symptom, so a row carrying
        # it quotes something nobody did, and the cap on attempts per subject
        # counts a phrase that comes out different every round.
        subject=the_subject_of(state.proposed_action)
    ):
        resumed = _what_the_earlier_attempt_left(
            state, already_taken, change_landed, publisher
        )

        # `None` means the earlier attempt left nothing behind - the claim was
        # written and the change never reached the provider - so this walk
        # takes the action that claim was for, on the claim already in hand.
        if resumed is not None:
            return resumed

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION), publisher)
    # Published from here rather than from inside Mitigation, which is not
    # incident-scoped: neither `take_action` nor `Action` carries an incident,
    # and threading one through an agent purely so it can narrate would put a
    # field in the domain for the account's benefit.
    publish(
        ActionTaken(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            action_type=state.proposed_action.action_type,
            subject=the_subject_of(state.proposed_action),
            enabled=the_direction_of(state.proposed_action)
        ),
        publisher
    )

    # The incident and the publisher travel with the action, so the wait for
    # the service to answer - the longest silence in an incident - is narrated
    # from inside Mitigation, where the looking actually happens. So does the
    # question of whether anybody still wants it: that wait is the one stretch
    # long enough for somebody to give up on it, and the only place in the walk
    # where a withdrawal is noticed anywhere but a node boundary.
    result = take(
        state.proposed_action,
        still_wanted=partial(still_wanted, state.incident_id),
        incident_id=state.incident_id,
        publisher=publisher
    )
    outcome = result.verdict

    # The verdict and the line reporting it, in that order and in one write.
    # Announced first, as it was, a walk that stopped in between left a verdict
    # every reader could see and no action recording it.
    complete_action(
        state.incident_id,
        # The candidate this attempt is about, named while it is still in hand.
        # Recovering it later means matching the flag the action and the
        # hypothesis happen to share, which the walk makes unambiguous only by
        # refusing to act on one subject twice - a rule about not retrying a
        # move, not about identity.
        hypothesis_id=state.hypothesis.id,
        outcome=outcome,
        undo_descriptor=result.undo_descriptor,
        narrating=VerdictReached(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            outcome=result.verdict
        )
    )
    # This candidate was genuinely tested: an action was taken and the service
    # was measured afterwards. The verdict is the answer it was tested for, so
    # it belongs on the candidate's own row and not only on the timeline - a
    # list of explanations with no sign of which one the walk was on is a list
    # nobody can read the incident from.
    #
    # Unless the attempt was abandoned, in which case nothing was measured and
    # the candidate learns nothing. Marking it tested would leave the incident
    # claiming an explanation was ruled out by an experiment that never
    # finished. The action row above still carries the change and its undo,
    # because the flag really was set and something has to put it back.
    if state.hypothesis is not None and result.verdict is not Verdict.WITHDRAWN:
        record_outcome(state.hypothesis.id, tested=True, result=outcome)

    return StateDelta(
        action_outcome=outcome,
        narration=Narration(action="mitigation attempted", detail=result.detail)
    )


def _what_the_earlier_attempt_left(state: IncidentState,
                                   already_taken: ActionAlreadyTaken,
                                   change_landed: ChangeLanded,
                                   publisher: Publisher
                                   ) -> StateDelta | None:
    """What a walk resumed inside the mitigation node should answer with, or
    `None` where it should simply take the action itself.

    Three states, and the whole point is that they are three rather than one.

    An outcome on file means the earlier attempt finished: this walk reports it
    and lets the routing continue as though it had reached it. The recorded
    outcome rather than a word of its own, because everything downstream reads
    `action_outcome` as a verdict and a new spelling would have to be
    understood in every one of those places.

    No outcome means the worker died mid-action. The provider's log is asked
    whether the change actually landed, under the flag the *action* names -
    the log answers about a flag it recorded moving, where the candidate says
    only what a model thought was wrong. It is the only record of what a
    process that no longer exists managed to do. If the change did land, the
    incident escalates: a change was made and nobody measured what followed,
    and neither acting again nor inventing a verdict would produce that
    measurement.

    If the change never landed, nothing happened at all - so this walk takes
    the action, on the claim already written.

    A provider that cannot say is treated as the first case, not the second. An
    unanswerable question is not a "no", and acting on it would be acting on a
    guess about whether production has already been changed.

    An action that leaves nothing behind is never asked about, and reaches that
    same case. A restart writes to no provider, so no log anywhere says whether
    the dead worker managed it - and a second restart taken on that guess is
    the loop the per-subject cap exists to prevent, arrived at by another road.

    An outcome nobody here can read is the fourth state, and it escalates
    without asking the provider anything. A verdict was reached, so the
    question this node asks a claim carrying nothing - did the change land -
    is not the question: a "yes" would describe an unmeasured change that was
    in fact measured, and a "no" would be read as licence to act again on a
    subject somebody already settled.
    """
    assert state.hypothesis is not None and state.proposed_action is not None

    claimed = already_taken(state.incident_id, hypothesis_id=state.hypothesis.id)
    outcome = claimed.outcome if claimed is not None else None

    if isinstance(outcome, UnreadVerdict):
        return StateDelta(
            status=IncidentStatus.ESCALATED,
            narration=Narration(
                action="mitigation resumed",
                detail=f"an earlier attempt already acted on this explanation, and "
                       f"recorded an outcome this version cannot read: {outcome}"
            )
        )

    if outcome is not None:
        # The account of the gap, and not of the verdict: that was published by
        # the walk that reached it, in the transaction that recorded it. This
        # says a second walk picked the incident up and read the answer back,
        # which is the difference between Argus having tried once and twice.
        #
        # Published rather than narrated because this branch moves the incident
        # only for two of its three outcomes - a refuted attempt leaves it
        # mitigating - and an account that appeared for some verdicts and not
        # others is worse than none.
        publish(
            MitigationResumed(
                incident_id=state.incident_id,
                hypothesis_id=state.hypothesis.id,
                outcome=outcome
            ),
            publisher
        )

        return StateDelta(
            action_outcome=outcome,
            narration=Narration(
                action="mitigation resumed",
                detail=f"an earlier attempt already acted on this explanation: "
                       f"{outcome}"
            )
        )

    # Both are needed to ask the question at all: which flag, and from when. A
    # claim whose moment cannot be read is a question that cannot be put -
    # which is the same answer as a provider that will not answer it.
    #
    # The flag comes from the action rather than from the candidate, because
    # the provider's log answers about a flag it recorded moving and the
    # candidate says what a model thought was wrong. And an action that leaves
    # nothing behind is not asked about at all: a restart writes to no
    # provider, so no log says whether the dead worker managed it, and that
    # unanswerable question ends the same way every unanswerable one does.
    since = claimed.claimed_at if claimed is not None else None
    landed = (
        change_landed(the_subject_of(state.proposed_action), since)
        if since is not None
        and leaves_something_to_put_back(state.proposed_action.action_type)
        else None
    )

    if landed is False:
        return None

    return StateDelta(
        status=IncidentStatus.ESCALATED,
        narration=Narration(
            action="mitigation resumed",
            detail=_why_the_resumed_walk_stopped(landed)
        )
    )


def _why_the_resumed_walk_stopped(landed: bool | None) -> str:
    """The two ways a resumed attempt ends the incident rather than continuing
    it, told apart in the words a human reads.

    A change that landed and a change nobody can account for are the same
    decision and different situations: the first needs somebody to look at the
    service, the second needs somebody to establish what the earlier attempt
    managed before it stopped.

    The second is not always a provider that would not answer. An action
    leaving nothing behind is never asked about in the first place - there is
    no log of a restart to consult - so the words say that nothing can account
    for the change rather than naming a provider that may never have been
    involved.
    """
    if landed:
        return ("an earlier attempt changed this flag and stopped before "
                "measuring what followed")

    return ("an earlier attempt claimed this action and nothing can say "
            "whether it was carried out")


def _nothing_to_act_on() -> StateDelta:
    """The unreachable case, handled rather than assumed away.

    The gate escalates an unproposed action, so nothing should arrive here
    without one. A node that indexed into `None` on the day that stopped being
    true would fail inside a state-changing step, which is the worst place to
    discover it.
    """
    return StateDelta(
        action_outcome=Verdict.ESCALATED,
        narration=Narration(
            action="mitigation attempted",
            detail="no action reached the mitigation step"
        )
    )


def route_after_mitigation(state: IncidentState) -> str:
    """A confirmed action goes on to look for a permanent fix; anything else
    that left the world intact hands over to the walk.

    A mitigation that worked is not the end of the incident, and this is where
    that stopped being pretended. The symptom is gone and the fault that caused
    it is still in the code with a flag holding it off, so the incident carries
    on to Code-Fix - which is why `fixing` is reached by two different roads
    now. The other one is Argus running out of mitigations it may take; this one is
    Argus having made one that worked.

    A refuted action stays in `mitigating` and goes to the node that decides
    whether another explanation is left to try.

    An `escalated` outcome still ends things immediately: the action could not
    be taken at all, so nothing was changed and nothing was measured, and a
    further experiment would run against a world Argus cannot describe.
    """
    if state.status == IncidentStatus.MITIGATED:
        return FIXING_ROUTE
    if state.status == IncidentStatus.MITIGATING:
        return NEXT_CANDIDATE_ROUTE
    return ESCALATED_ROUTE
