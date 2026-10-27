"""Performing the action the gate admitted, and recording what came of it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from functools import partial

from agent_mitigation import Verdict
from argus_core import utc_now, was_lost
from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    MitigationResumed,
    PlatformUnavailable,
    Publisher,
    VerdictReached,
    nobody,
    publish,
)
from argus_core.models import (
    FLAG_PROVIDER,
    Action,
    ActionProgress,
    Actor,
    AlarmClaim,
    IncidentStatus,
    UndoDescriptor,
    UnreadVerdict,
    the_accelerator_of,
    the_actions_through,
    the_direction_of,
    the_platform_of,
    the_service_addressed_by,
    the_subject_of,
)
from argus_incidents import IsStillWanted

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import (
    ActionAlreadyTaken,
    AdvanceAction,
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

logger = logging.getLogger(__name__)


def mitigation_node(
    state: IncidentState,
    record_action: RecordAction,
    complete_action: CompleteAction,
    already_taken: ActionAlreadyTaken,
    advance_action: AdvanceAction,
    record_outcome: RecordOutcome,
    still_wanted: IsStillWanted,
    take: TakeAction,
    change_landed: ChangeLanded,
    publisher: Publisher = nobody,
    now: Callable[[], datetime] = utc_now
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

    `now` is the clock the action is dated by, and the walk carries that date
    on to the attempt it remembers.

    `advance_action` writes on the claim what is learnt before the verdict:
    that the change was made, the moment the agent says so, with what would
    put it back - so a worker that dies during the wait leaves a row a
    withdrawal can undo and a write-up can call tried.
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
        subject=the_subject_of(state.proposed_action),
        # When the claim was written, which is not when the action was: the
        # agent is called in after it, and the action announced after that.
        # Dated by the claim, the action came before the agent that took it -
        # so what dates the action is its announcement.
        at=now()
    ):
        resumed = _what_the_earlier_attempt_left(
            state, already_taken, change_landed, advance_action, publisher
        )

        # `None` means the earlier attempt left nothing behind - the claim was
        # written and the change never reached the provider - so this walk
        # takes the action that claim was for, on the claim already in hand.
        if resumed is not None:
            return resumed

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION), publisher)
    # The announcement, once the agent says the change was made - and none for
    # an attempt that ended before its write, which its verdict says instead.
    announced: list[ActionTaken] = []

    # The incident and the publisher travel with the action, so the
    # verification wait - the longest silence in an incident - is narrated
    # from inside Mitigation, where the looking actually happens. So does the
    # question of whether anybody still wants it: that wait is the one stretch
    # long enough for somebody to give up on it, and the only place in the walk
    # where a withdrawal is noticed anywhere but a node boundary.
    # The minute the alert dated the incident to travels with them, because the
    # wait has one more question to answer than a level: whether any of this
    # incident's own minutes were ever published. Read off the alert rather than
    # derived here, since the alert is the only thing that ever states one.
    result = take(
        state.proposed_action,
        still_wanted=partial(still_wanted, state.incident_id),
        incident_id=state.incident_id,
        publisher=publisher,
        onset=state.alert.stated_onset,
        # The minute the investigation dated the incident from, so the recovery
        # is never dated before it.
        incident_began=state.onset.minute if state.onset is not None else None,
        # The rule that paged, where the alert is about a series - the action is
        # judged by whether it stops firing. A finding's check runs on its own
        # schedule, so it keeps the confirmation it has.
        rule=(
            state.alert.rule
            if state.alert.claim is AlarmClaim.A_SERIES_CONDITION
            else None
        ),
        change_made=partial(
            _the_change_was_made,
            advance_action,
            announced,
            publisher,
            now,
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            action=state.proposed_action,
            alerting_service=state.alert.service
        )
    )
    # When the change was made, for the round that remembers the attempt - and
    # nothing where none was: an action never performed is no attempt a later
    # round may be told was refuted.
    acted_at = announced[0].at if announced else None
    outcome = result.verdict
    logger.info("verdict reached", extra={
        "verdict": outcome,
        "action_type": state.proposed_action.action_type,
        "subject": the_subject_of(state.proposed_action)
    })

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
        performed=result.performed,
        narrating=VerdictReached(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            outcome=result.verdict,
            # What was reached for, and whether it was done: for an attempt
            # that ended before its write, this is the only line saying so.
            action_type=state.proposed_action.action_type,
            subject=the_subject_of(state.proposed_action),
            performed=result.performed,
            judged=result.judged
        )
    )
    # This candidate was genuinely tested: an action was taken and the service
    # was watched to a verdict afterwards. The verdict is the answer it was
    # tested for, so it belongs on the candidate's own row and not only on the
    # timeline - a list of explanations with no sign of which one the walk was
    # on is a list nobody can read the incident from.
    #
    # Unless nothing was judged, in which case the candidate learns nothing.
    # Marking it tested would leave the incident claiming an explanation was
    # ruled out by an experiment that reached no verdict - an abandoned
    # attempt, or a wait whose every look at the service went unanswered. The
    # action row above still carries the change and its undo, because the flag
    # really was set and something has to put it back.
    #
    # Two clauses, and they answer different questions. A stop judges nothing
    # by definition - a person ended the incident, whatever the outcome says
    # about itself - so the verdict settles it here and an outcome that forgot
    # to say cannot talk the walk out of it. Everything else has to be asked,
    # because the verdict does not tell: `ESCALATED` is the word for a wait that
    # never saw the service *and* for a refutation whose change could not be put
    # back, and the second of those judged it.
    if (
        state.hypothesis is not None
        and result.verdict is not Verdict.STOPPED
        and result.judged
    ):
        record_outcome(state.hypothesis.id, tested=True, result=outcome)

    if result.verdict is Verdict.PLATFORM_UNREACHABLE:
        # Recorded here because here is the only place that holds both halves:
        # the verdict, and the action it came back from. Which platform an
        # action acts through is a property of its kind, so the platform is
        # derived from the action rather than named - the same verdict off a
        # flag revert means the flag provider is what did not answer, and a
        # node that wrote the deployment platform either way would have the
        # walk pass over three candidates that were never affected.
        #
        # Added to what the walk already carries rather than replacing it, so a
        # second platform failing does not forget the first.
        platform = the_platform_of(state.proposed_action.action_type)
        # Published here because here is where it was learnt, and before the
        # candidate that follows - the stream is read as a story in the order it
        # happened, and an event explaining why later candidates went untried is
        # only an explanation if it stands before them.
        #
        # By the walk rather than by the tier whose call failed. The tier
        # reported a failed call, which is not yet the fact that a platform is
        # unavailable to *this incident*, and a tier publishing against an
        # incident would be publishing about work it cannot see the shape of.
        #
        # Once, not once per candidate passed over: the fact is about the
        # platform, and this is the only place it is learnt.
        publish(
            PlatformUnavailable(
                incident_id=state.incident_id,
                platform=platform,
                actions_unavailable=the_actions_through(platform)
            ),
            publisher
        )

        return StateDelta(
            action_outcome=outcome,
            action_because=result.because,
            acted_at=acted_at,
            unreachable_platforms=[*state.unreachable_platforms, platform],
            narration=Narration(action="mitigation attempted", detail=result.detail)
        )

    return StateDelta(
        action_outcome=outcome,
        # Carried for the round that reads this attempt, which is told how it
        # did not help and nothing else about it.
        action_because=result.because,
        acted_at=acted_at,
        narration=Narration(action="mitigation attempted", detail=result.detail)
    )


def _whose_dependency_was_acted_on(action: Action,
                                   alerting_service: str) -> str | None:
    """The service this action's subject is a dependency of, where it is one.

    `None` for the ordinary incident, in which the action is addressed to the
    service that alerted and there is nothing to explain. A name where it is
    not: Argus has just acted on something it was never paged about, and the
    reason it was allowed to - that the alerting service calls this one - lives
    in a register that an account of the incident cannot reach.

    Said here because this is the only party holding both halves. The agent
    that takes the action is not incident-scoped, and whatever renders the
    account is given events rather than the incident, so neither of them can
    compare the address against the service the alert named.

    It does not consult the register. What put this action past the gate is
    already the register's answer, and asking a second time would be a second
    answer able to disagree with the one authority rested on - so what is said
    is what is true of the address by construction: it is not the service that
    alerted.

    The address rather than the subject, which is the same distinction the gate
    draws and for the same reason. A flag's name is never the service that
    alerted, so deciding this by subject would announce every revert Argus makes
    as acting on a dependency - the clause meant to mark the unusual incident
    marking the commonest one instead.
    """
    addressed_to = the_service_addressed_by(action)

    if addressed_to is None or addressed_to == alerting_service:
        return None

    return alerting_service


def _the_change_was_made(advance_action: AdvanceAction,
                         announced: list[ActionTaken],
                         publisher: Publisher,
                         now: Callable[[], datetime],
                         undo_descriptor: UndoDescriptor | None,
                         *,
                         incident_id: str,
                         hypothesis_id: str,
                         action: Action,
                         alerting_service: str) -> None:
    """Puts on the claim that its change was made, and what would put it back
    - then says so, dated now, into `announced`.

    A write that fails is logged and the attempt goes on. The change is made
    by now, and the wait that follows is what judges it: abandoning it over a
    record would leave the world changed and unmeasured, where carrying on
    loses only an early copy - the completion writes the same facts again once
    the wait has a verdict. The early copy only ever mattered to a worker that
    dies during the wait, and this one is alive. All but a write refused for a
    lost run, which is no early copy: the walk no longer holds its run, and a
    wait from here would be nobody's walk watching production for minutes.

    Announced here and nowhere earlier: before the write, an attempt the
    platform refused was told as done. Published from the walk rather than
    from inside Mitigation, which is not incident-scoped: neither `take_action`
    nor `Action` carries an incident, and threading one through an agent purely
    so it can narrate would put a field in the domain for the account's benefit.
    """
    try:
        advance_action(incident_id, hypothesis_id=hypothesis_id,
                       to=ActionProgress.PERFORMED, undo_descriptor=undo_descriptor)
    except Exception as error:
        if was_lost(error):
            raise

        logger.warning("the change could not be recorded as made before the wait",
                       exc_info=True,
                       extra={"incident_id": incident_id, "hypothesis_id": hypothesis_id})

    announcement = ActionTaken(
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        action_type=action.action_type,
        subject=the_subject_of(action),
        enabled=the_direction_of(action),
        a_dependency_of=_whose_dependency_was_acted_on(action, alerting_service),
        accelerator=the_accelerator_of(action),
        at=now()
    )
    publish(announcement, publisher)
    announced.append(announcement)


def _what_the_earlier_attempt_left(state: IncidentState,
                                   already_taken: ActionAlreadyTaken,
                                   change_landed: ChangeLanded,
                                   advance_action: AdvanceAction,
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

    No outcome means the worker died mid-action, and the claim's progress says
    how far it got. Told as made, the change was made: the incident escalates
    without asking anybody, since a change was made and nobody recorded what
    came of it, and neither acting again nor inventing a verdict would produce
    that record. Told as unknown, an earlier resume already failed to find out,
    and the incident escalates on that - asking again could only be read as
    licence to act a second time on a change somebody may already have made.

    Still only claimed, the provider's log is asked whether the change actually
    landed, under the flag the *action* names - the log answers about a flag it
    recorded moving, where the candidate says only what a model thought was
    wrong. It is the only record of what a process that no longer exists
    managed to do. If the change did land, the claim is told so and the
    incident escalates as above.

    If the change never landed, nothing happened at all - so this walk takes
    the action, on the claim already written.

    A provider that cannot say is treated as the first case, not the second. An
    unanswerable question is not a "no", and acting on it would be acting on a
    guess about whether production has already been changed. The claim is told
    that nobody can say, which is final: no walk will ask it again.

    An action that does not go through the flag provider is never asked about,
    and reaches that same case. The provider's log answers about flags: asked
    about a "flag" named after a deployment it finds no such change, and that
    "no" would have this walk roll back, scale or pin a second time a deployment
    the dead worker may already have changed. Nothing else keeps a log that
    says whether Argus's own change to a deployment landed - a restart writes to
    nothing at all - and a second action taken on that guess is the loop the
    per-subject cap exists to prevent, arrived at by another road.

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

    if claimed is not None and outcome is not None:
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

        # The moment the claim was written, just before the action was taken.
        # The walk that announced it is gone, and the row is all that is left.
        return StateDelta(
            action_outcome=outcome,
            # Told outright: the claim records the verdict and not the reason,
            # and left unset the walk would keep an earlier round's reason and
            # hand it on as this action's.
            action_because=None,
            acted_at=claimed.claimed_at,
            narration=Narration(
                action="mitigation resumed",
                detail=f"an earlier attempt already acted on this explanation: "
                       f"{outcome}"
            )
        )

    # Already answered on the claim, so nobody is asked. Made is made, whoever
    # the provider would credit with it; and unknown was an earlier resume's
    # answer that nobody can say, which asking again cannot improve on.
    if claimed is not None and claimed.progress is ActionProgress.PERFORMED:
        return _the_resumed_walk_stops(landed=True)

    if claimed is not None and claimed.progress is ActionProgress.UNKNOWN:
        return _the_resumed_walk_stops(landed=None)

    # Both are needed to ask the question at all: which flag, and from when. A
    # claim whose moment cannot be read is a question that cannot be put -
    # which is the same answer as a provider that will not answer it.
    #
    # The flag comes from the action rather than from the candidate, because
    # the provider's log answers about a flag it recorded moving and the
    # candidate says what a model thought was wrong. And an action through any
    # other platform is not asked about at all: the provider's log knows
    # nothing of a deployment, so its "no" would be a guess read as a fact, and
    # that unanswerable question ends the same way every unanswerable one does.
    since = claimed.claimed_at if claimed is not None else None
    landed = (
        change_landed(the_subject_of(state.proposed_action), since)
        if since is not None
        and the_platform_of(state.proposed_action.action_type) == FLAG_PROVIDER
        else None
    )

    if landed is False:
        return None

    # The answer kept on the claim, so the next walk to find it - the one
    # resumed after this one dies before escalating - reads it rather than
    # asking again. Not where no claim was found: there is no row to keep it.
    if claimed is not None:
        advance_action(
            state.incident_id,
            hypothesis_id=state.hypothesis.id,
            to=ActionProgress.PERFORMED if landed else ActionProgress.UNKNOWN,
            # What the dead worker was told would put it back went with it.
            undo_descriptor=None
        )

    return _the_resumed_walk_stops(landed)


def _the_resumed_walk_stops(landed: bool | None) -> StateDelta:
    """The incident handed to a person by a resumed walk that cannot carry
    the earlier attempt on."""
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

    The first names the action rather than a flag. A change told as made
    before the wait can be any kind of action, a rollback as much as a flag.
    And it says the attempt stopped before *recording* what came of it rather
    than before measuring it: a verdict can be reached and the worker die
    before writing it, and the row cannot tell the two apart.

    The second is not always a provider that would not answer. An action
    through any platform but the flag provider is never asked about in the
    first place - there is no log of a restart or a rollback to consult - so the
    words say that nothing can account for the change rather than naming a
    provider that was never involved.
    """
    if landed:
        return ("an earlier attempt carried out this action and stopped before "
                "recording what came of it")

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
        # Nothing was watched, and an earlier round's reason is not this one's.
        action_because=None,
        narration=Narration(
            action="mitigation attempted",
            detail="no action reached the mitigation step"
        )
    )


def route_after_mitigation(state: IncidentState) -> str:
    """A confirmed action goes on to look for a permanent fix; anything else
    that left the world intact hands over to the walk.

    A mitigation that worked does not resolve the incident. The symptom is gone
    and the fault that caused it is still in the code with a flag holding it
    off, so the walk carries on to Code-Fix - with the incident `mitigated`,
    which it stays whatever Code-Fix finds. Another road to Code-Fix is
    `fixing`, Argus running out of mitigations it may take; this one is Argus
    having made one that worked.

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
