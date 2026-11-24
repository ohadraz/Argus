"""Performing the action the gate admitted, and recording what came of it."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any, Final

from core import parse_iso, utc_now, was_lost
from core.autonomy import Admitted, admit
from core.events import (
    ActionRefused,
    ActionTaken,
    AgentInvoked,
    MitigationResumed,
    PlatformUnavailable,
    Publisher,
    VerdictReached,
    nobody,
    publish,
)
from core.models import (
    Action,
    ActionProgress,
    Actor,
    AlarmClaim,
    AlreadyClaimed,
    ChangeFound,
    IncidentStatus,
    Made,
    NotMade,
    Planned,
    Refusal,
    SubjectOpen,
    UndoDescriptor,
    UnreadVerdict,
    the_actions_through,
    the_kind,
    whose_open_change,
    why_it_was_refused,
)
from incident_record import IsStillWanted
from mcp_transport import LostAfterSending
from mitigation import (
    NobodyCanSay,
    Outcome,
    Verdict,
    performed_as_recorded,
    stopped_before_it_was_taken,
)

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import (
    ActingFor,
    ActionAlreadyTaken,
    AdvanceAction,
    ClaimedAction,
    CompleteAction,
    OweAPutBack,
    PlanAction,
    RecordAction,
    RecordOutcome,
    Resuming,
    TakeAction,
)
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    NEXT_CANDIDATE_ROUTE,
)
from orchestrator.walk.state import Confirmed, Ending, Escalated, IncidentState

logger = logging.getLogger(__name__)

# How a resumed walk hands an incident over, in the words a person reads. A
# change made and a change nobody can account for are the same decision and
# different situations: the first needs somebody to look at the service, the
# second somebody to establish what the earlier attempt managed. Named for the
# action rather than a flag, since a change told as made can be any kind.
_A_CHANGE_MADE_AND_NEVER_RECORDED: Final = (
    "an earlier attempt carried out this action and stopped before recording what came "
    "of it"
)
_A_CHANGE_NOBODY_CAN_ACCOUNT_FOR: Final = (
    "an earlier attempt claimed this action and nothing can say whether it was carried out"
)
_CHANGED_SINCE_IT_WAS_MADE: Final = (
    "an earlier attempt carried out this action, and it has been changed since"
)
_NOBODY_CAN_SAY_IT_STILL_STANDS: Final = (
    "an earlier attempt carried out this action, and nothing can say whether it still "
    "stands as it was left"
)
_THE_METRICS_NO_LONGER_REACH_BACK: Final = (
    "the metrics kept no longer reach back to when the incident began, so whether the "
    "change helped cannot be judged"
)
# What a person reading the incident is told of an action asked for whose
# answer never came back.
_A_CHANGE_LOST_AFTER_IT_WAS_ASKED_FOR: Final = (
    "this action was asked for and its answer never came back, so nothing can "
    "say whether it was carried out"
)


def mitigation_node(
    state: IncidentState,
    record_action: RecordAction,
    complete_action: CompleteAction,
    already_taken: ActionAlreadyTaken,
    advance_action: AdvanceAction,
    owe_a_put_back: OweAPutBack,
    record_outcome: RecordOutcome,
    still_wanted: IsStillWanted,
    take: TakeAction,
    plan_action: PlanAction,
    resuming: Resuming,
    acting_for: ActingFor,
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
    put it back and when it was made - so a worker that dies during the wait
    leaves a row a withdrawal can undo and a write-up can call tried.

    `resuming` is what a walk refused the claim reads of the estate and
    carries on with: the claim was written by a worker that is gone, and the
    walk picks its attempt up at the step the row records (spec §11.1).

    `owe_a_put_back` writes on the claim that the wait refuted a change that
    left something to put back, with what it found, before the put-back is
    attempted - so a worker that dies putting it back leaves the change owed
    back on record.

    `acting_for` makes the claim's action the one the write tier marks every
    change of this attempt with (`Holding.acting_for`).

    `plan_action` works out, before the claim, the change the action will
    make: the claim carries it from the moment it is written, and the action is
    taken on it. A plan the tier refused is the attempt's outcome, recorded on
    the claim as the same refusal from the write was - and nothing is taken.

    The action is admitted here again, by the policy the gate asked
    (`core.autonomy.admit`), before anything is planned or claimed. Not because
    the gate's answer is doubted: `take` accepts only an admission, and an
    admission is never carried in the walk's state - a checkpoint is data, and a
    proof that could be read back from one could be written into one. Asked of
    the same action, alert and register, it answers as the gate did, on the
    live walk and on one resumed after its worker died alike. Where it does not
    - an edge into this node that bypassed the gate, or a declared set or
    register narrowed between the gate and a resume - nothing new is written.
    With no earlier claim on the candidate, nothing is planned, claimed or
    taken, and the incident is handed to a person. With one, the earlier
    attempt is picked up as any resumed walk picks it up - a change it made is
    still watched, and still put back where it is owed back, since neither is a
    new change - and only taking the action again is refused.
    """
    # Both, because an action is taken *for* a candidate: one without the other
    # is not an attempt this node can account for, and recording it would leave
    # a row nothing can attribute. The gate guarantees both are here; this says
    # so in a way the type checker can read.
    if state.action is None or state.cursor.hypothesis is None:
        return _nothing_to_act_on()

    admission = admit(state.action.proposed_action,
                      alerting_service=state.alert.service,
                      dependencies=state.evidence.dependencies)

    if isinstance(admission, Refusal):
        # The claim is read before anything is refused, since a refusal is about
        # writing anew and an earlier attempt may have written already: what it
        # made is still watched or put back, refused or not. Read rather than
        # claimed, because a claim is a new attempt and this is not one.
        claimed = already_taken(state.incident_id, hypothesis_id=state.cursor.hypothesis.id)

        if claimed is None:
            return _not_admitted(state, admission, record_outcome, publisher)

        return _the_earlier_attempt_resumed(
            state,
            claimed,
            _Resumption(
                admission=admission, planned=None, refused=None, resuming=resuming,
                take=take, complete_action=complete_action, advance_action=advance_action,
                owe_a_put_back=owe_a_put_back, record_outcome=record_outcome,
                still_wanted=still_wanted, acting_for=acting_for, publisher=publisher,
                now=now
            )
        )

    # Before the claim, so the claim carries what the write will compare the
    # estate with from the moment it exists: a plan made after it leaves a claim
    # a resumed walk has nothing to compare with, for exactly the stretch it is
    # likeliest to be resumed in. A plan changes nothing, so a walk that loses
    # the claim below has changed nothing by planning.
    planning = plan_action(state.action.proposed_action)
    planned = planning if isinstance(planning, Planned) else None
    refused = planning if isinstance(planning, Outcome) else None

    # When the claim was written, which is not when the action was: the agent is
    # called in after it, and the action announced after that. Recorded as the
    # claim's time, the action came before the agent that took it - so what the
    # record says it was taken at is its announcement. Kept here because it is
    # what the action is dated from: after the plan's read and before the write,
    # the latest moment known to come before the write was sent, and on the
    # walk's own clock, as the change's arrival and the deadlines are. Never the
    # write's answer, which can come back a minute after the service acted - and
    # the service restores its rows from its own minute of the change, which,
    # counted as before the action, read as the sight having been there.
    claimed_at = now()

    # The claim goes in before anything happens, so that a walk resumed inside
    # this node is refused by the database rather than by a check it could race
    # with. Losing it means an earlier attempt already acted on this candidate -
    # or that another change to the same subject may still stand, beside which
    # Argus does not act. Its id is what every write the action makes is marked
    # with.
    answered = record_action(
        state.incident_id,
        hypothesis_id=state.cursor.hypothesis.id,
        action_type=state.action.proposed_action.action_type,
        # What the action acts on, not what the candidate calls the fault. The
        # row is the only account of what this attempt changed, and every
        # reader of it afterwards - the write-up, and the memory the next
        # incident is ordered by - has nowhere else to ask. A candidate's
        # subject is never an address, and is often prose a model wrote about
        # the symptom, so a row carrying it quotes something nobody did, and the
        # cap on attempts per subject counts a phrase that comes out different
        # every round.
        subject=state.action.proposed_action.subject,
        at=claimed_at,
        # Absent for an action with nothing to plan, and for a plan the tier
        # refused, since none was made.
        planned=planned
    )

    if isinstance(answered, SubjectOpen):
        return _the_subject_is_open(state, answered.open_in, record_outcome, publisher)

    if isinstance(answered, AlreadyClaimed):
        return _the_earlier_attempt_resumed(
            state,
            already_taken(state.incident_id, hypothesis_id=state.cursor.hypothesis.id),
            _Resumption(
                admission=admission, planned=planned, refused=refused, resuming=resuming,
                take=take, complete_action=complete_action, advance_action=advance_action,
                owe_a_put_back=owe_a_put_back, record_outcome=record_outcome,
                still_wanted=still_wanted, acting_for=acting_for, publisher=publisher,
                now=now
            )
        )

    action_id = answered.action_id
    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION), publisher)
    # The announcement, once the agent says the change was made - and none for
    # an attempt that ended before its write, which its verdict says instead.
    announced: list[ActionTaken] = []

    # A plan the tier refused is the attempt: nothing is taken, and the refusal
    # is recorded on the claim below exactly as the same refusal from the write
    # was - so the cap on attempts per subject, the write-up and the memory of
    # what was tried all read the row they always read. Unless a person ended
    # the incident meanwhile, which `take` asks before it does anything and so
    # is asked here in its place: then the attempt is the stop, as it would
    # have been had the plan been made.
    if refused is not None:
        result = (refused if still_wanted(state.incident_id)
                  else stopped_before_it_was_taken())
    else:
        try:
            result = _take_on_the_claim(
                state, take, admission, planned, claimed_at, action_id, acting_for,
                still_wanted, advance_action, owe_a_put_back, announced, publisher, now
            )
        except LostAfterSending:
            logger.warning("the action was asked for and its answer was lost",
                           exc_info=True, extra={"incident_id": state.incident_id})

            return _nobody_can_say_whether_it_was_carried_out(state, advance_action, planned)
    # When the change was made, for the round that remembers the attempt - and
    # nothing where none was: an action never performed is no attempt a later
    # round may be told was refuted.
    acted_at = announced[0].at if announced else None
    logger.info("verdict reached", extra={
        "verdict": result.verdict,
        "action_type": state.action.proposed_action.action_type,
        "subject": state.action.proposed_action.subject
    })

    return _the_attempt_recorded(state, result, acted_at, complete_action, record_outcome,
                                 publisher)


def _take_on_the_claim(state: IncidentState,
                       take: TakeAction,
                       admitted: Admitted[Action],
                       planned: Planned[Any] | None,
                       acted_from: datetime,
                       action_id: str,
                       acting_for: ActingFor,
                       still_wanted: IsStillWanted,
                       advance_action: AdvanceAction,
                       owe_a_put_back: OweAPutBack,
                       announced: list[ActionTaken],
                       publisher: Publisher,
                       now: Callable[[], datetime]) -> Outcome:
    """Takes the claimed action on its plan, inside the claim's action, and
    answers with what came of it."""
    # Inside the claim's action, put-back of a refuted change included, so that
    # every write the tier makes for it carries its mark.
    with acting_for(action_id):
        return _taken(state, take, admitted, planned, acted_from, still_wanted,
                      advance_action, owe_a_put_back, announced, publisher, now)


def _taken(state: IncidentState,
           take: TakeAction,
           admitted: Admitted[Action],
           planned: Planned[Any] | None,
           acted_from: datetime,
           still_wanted: IsStillWanted,
           advance_action: AdvanceAction,
           owe_a_put_back: OweAPutBack,
           announced: list[ActionTaken],
           publisher: Publisher,
           now: Callable[[], datetime]) -> Outcome:
    """Takes the admitted action on its plan, for whichever claim its caller
    acts for, and answers with what came of it."""
    assert state.cursor.hypothesis is not None

    return take(
        admitted,
        # The plan the claim carries - this walk's, or on a resume the
        # earlier claim's - and not one worked out again: the write
        # compares the estate with what the claim recorded.
        plan=planned,
        acted_from=acted_from,
        **_what_the_wait_is_handed(state, still_wanted, publisher),
        change_made=partial(
            _the_change_was_made,
            advance_action,
            announced,
            publisher,
            now,
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id,
            candidate_number=state.cursor.hypothesis.number,
            action=admitted.action,
            alerting_service=state.alert.service
        ),
        put_back_owed=partial(
            _the_put_back_is_owed,
            owe_a_put_back,
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id
        )
    )


def _what_the_wait_is_handed(state: IncidentState,
                             still_wanted: IsStillWanted,
                             publisher: Publisher) -> dict[str, Any]:
    """What the verification wait is handed of the incident, whoever made the
    change it waits on.

    The incident and the publisher travel with the action, so the verification
    wait - the longest silence in an incident - is narrated from inside
    Mitigation, where the looking actually happens. So does the question of
    whether anybody still wants it: that wait is the one stretch long enough
    for somebody to give up on it, and the only place in the walk where a
    withdrawal is noticed anywhere but a node boundary. The minute the alert
    dated the incident to travels with them, because the wait has one more
    question to answer than a level: whether any of this incident's own
    minutes were ever published. Read off the alert rather than derived here,
    since the alert is the only thing that ever states one.
    """
    return {
        "still_wanted": partial(still_wanted, state.incident_id),
        "incident_id": state.incident_id,
        "publisher": publisher,
        "onset": state.alert.stated_onset,
        # The minute the investigation dated the incident from, so the
        # recovery is never dated before it.
        "incident_began": state.history.onset.minute if state.history.onset is not None else None,
        # The rule that paged, where the alert is about a series - the action
        # is judged by whether it stops firing. A finding's check runs on its
        # own schedule, so it keeps the confirmation it has.
        "rule": (
            state.alert.rule
            if state.alert.claim is AlarmClaim.A_SERIES_CONDITION
            else None
        )
    }


def _the_subject_is_open(state: IncidentState,
                         open_in: str | None,
                         record_outcome: RecordOutcome,
                         publisher: Publisher) -> StateDelta:
    """The incident handed to a person, nothing taken, where the claim was
    refused because another change of Argus's to the same subject may still
    stand - another incident's, or this one's own from an earlier candidate.

    Two changes open on one subject undo each other, so Argus does not act
    beside one, as it does not act beside a person's (`ChangedSince`). No
    action row was written, so nothing is completed: the candidate is kept as
    untested, with the reason, and the refusal is published as the gate's
    are - Slack and the postmortem's declined step read it there. Said as the
    attempt's outcome, escalated, so the status follows from it with that
    sentence.
    """
    assert state.cursor.hypothesis is not None and state.action is not None

    because = (why_it_was_refused(Refusal.SUBJECT_ALREADY_OPEN)
               + whose_open_change(open_in, state.incident_id))
    logger.info("action refused, another change to its subject may still stand",
                extra={"subject": state.action.proposed_action.subject,
                       "open_in": open_in})
    record_outcome(state.cursor.hypothesis.id, tested=False, result=because)
    publish(
        ActionRefused(
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id,
            candidate_number=state.cursor.hypothesis.number,
            refusal=Refusal.SUBJECT_ALREADY_OPEN,
            open_in=open_in
        ),
        publisher
    )

    return StateDelta(
        ending=Escalated(),
        narration=Narration(action="mitigation refused", detail=because)
    )


def _not_admitted(state: IncidentState,
                  refusal: Refusal,
                  record_outcome: RecordOutcome,
                  publisher: Publisher) -> StateDelta:
    """The incident handed to a person, nothing planned, claimed or taken,
    where the autonomy policy refused the action at the moment it came to be
    taken.

    The gate asked the same policy of the same action and was told yes, so this
    is reached only by a walk that came here some other way - an edge into this
    node that bypassed the gate - or by one resumed after the declared set or
    the register was narrowed under it, before it claimed anything. Neither is
    a judgement on this candidate alone, and the walk does not go on to the
    next: it stops, as `_the_subject_is_open` stops, with the refusal published
    as the gate's are and the candidate kept as untested, with the reason.
    Reached only where no earlier attempt holds a claim on the candidate: one
    that does is picked up as any resumed walk picks it up, and only taking the
    action again is refused (`_the_retake_refused`).
    """
    assert state.cursor.hypothesis is not None and state.action is not None

    because = why_it_was_refused(refusal)
    logger.warning("action not admitted when it came to be taken",
                   extra={"refusal": refusal,
                          "action_type": state.action.proposed_action.action_type,
                          "subject": state.action.proposed_action.subject})
    record_outcome(state.cursor.hypothesis.id, tested=False, result=because)
    publish(
        ActionRefused(
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id,
            candidate_number=state.cursor.hypothesis.number,
            refusal=refusal
        ),
        publisher
    )

    return StateDelta(
        ending=Escalated(),
        narration=Narration(action="mitigation refused", detail=because)
    )


def _nobody_can_say_whether_it_was_carried_out(state: IncidentState,
                                               advance_action: AdvanceAction,
                                               planned: Planned[Any] | None) -> StateDelta:
    """The incident handed to a person, its claim kept as nobody can say, after
    the action was asked for and its answer never came back.

    The claim's answer is the one a resumed walk gives a claim it cannot
    account for, so a walk resumed after this one reads it and asks nothing
    again. No verdict is written - there is no outcome, and a completed row
    would say the attempt ended in one - and nothing is announced, since
    nothing is known to have been done. A claim that cannot be moved on is
    logged and the incident handed over all the same (`_the_claim_is_told`).

    The claim keeps its plan's descriptor as what may be left behind, where
    the action had a plan: a suspension before its write may have landed, and
    the unwind's put-back reads the estate before it writes, so it puts back
    only what is Argus's. A restart or a discard has no plan, and keeps nothing.
    """
    _the_claim_is_told(state, advance_action, ActionProgress.UNKNOWN,
                       undo_descriptor=planned.descriptor if planned is not None else None)

    return StateDelta(
        ending=Escalated(),
        narration=Narration(action="mitigation attempted",
                            detail=_A_CHANGE_LOST_AFTER_IT_WAS_ASKED_FOR)
    )


def _the_attempt_recorded(state: IncidentState,
                          result: Outcome,
                          acted_at: datetime | None,
                          complete_action: CompleteAction,
                          record_outcome: RecordOutcome,
                          publisher: Publisher) -> StateDelta:
    """Records what came of the attempt on its claim and its candidate, and
    answers with what the walk carries on with - whether the action was taken
    or its plan refused."""
    assert state.action is not None and state.cursor.hypothesis is not None

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
        hypothesis_id=state.cursor.hypothesis.id,
        outcome=outcome,
        undo_descriptor=result.undo_descriptor,
        performed=result.performed,
        # What tells a refusal that asked for no change from one nobody can
        # account for, which the write-up says differently.
        left_behind_known=result.left_behind_known,
        # What putting a refuted change back did, so the cleanup after the
        # incident does not put it back a second time.
        undone=result.undone,
        narrating=VerdictReached(
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id,
            candidate_number=state.cursor.hypothesis.number,
            outcome=result.verdict,
            # What was reached for, and whether it was done: for an attempt
            # that ended before its write, this is the only line saying so.
            action_type=state.action.proposed_action.action_type,
            subject=state.action.proposed_action.subject,
            performed=result.performed,
            not_performed_because=result.not_performed_because,
            undone=result.undone,
            undone_detail=result.undone_detail,
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
        state.cursor.hypothesis is not None
        and result.verdict is not Verdict.STOPPED
        and result.judged
    ):
        record_outcome(state.cursor.hypothesis.id, tested=True, result=outcome)
    # Not performed, and a tier said why: the candidate was passed over untested,
    # and its row keeps the reason as the gate's refusals keep theirs - the one
    # thing a reader of the list has for why this explanation was never tried.
    # Untested, so nothing here reads as a verdict on it.
    elif (
        state.cursor.hypothesis is not None
        and not result.performed
        and result.not_performed_because is not None
    ):
        record_outcome(state.cursor.hypothesis.id, tested=False,
                       result=result.not_performed_because)

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
        platform = the_kind(state.action.proposed_action.action_type).platform
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
            ending=_the_ending_reached(outcome),
            action_because=result.because,
            acted_at=acted_at,
            unreachable_platforms=[*state.history.unreachable_platforms, platform],
            narration=Narration(action="mitigation attempted", detail=result.detail)
        )

    return StateDelta(
        ending=_the_ending_reached(outcome),
        # Carried for the round that reads this attempt, which is told how it
        # did not help and nothing else about it.
        action_because=result.because,
        acted_at=acted_at,
        narration=Narration(action="mitigation attempted", detail=result.detail)
    )


def _the_ending_reached(verdict: Verdict) -> Ending | None:
    """The ending a verdict brings the search for a mitigation to, where it
    brings it to one.

    Two of them do: a change the service recovered after, and one that settled
    nothing Argus can go on from. Every other verdict leaves the walk to its next
    candidate, or to a person who ended the incident.
    """
    if verdict is Verdict.CONFIRMED:
        return Confirmed()

    if verdict is Verdict.ESCALATED:
        return Escalated()

    return None


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
    addressed_to = action.service_addressed

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
                         candidate_number: int,
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
        # The walk's own moment for the change, read for the row just before it
        # is written - the clock the walk dates everything by, so a walk resumed
        # after this one dies dates the action by it. The announcement keeps the
        # reading it takes below, after the row.
        advance_action(incident_id, hypothesis_id=hypothesis_id,
                       to=ActionProgress.PERFORMED, undo_descriptor=undo_descriptor,
                       performed_at=now())
    except Exception as error:
        if was_lost(error):
            raise

        logger.warning("the change could not be recorded as made before the wait",
                       exc_info=True,
                       extra={"incident_id": incident_id, "hypothesis_id": hypothesis_id})

    announcement = ActionTaken(
        incident_id=incident_id,
        hypothesis_id=hypothesis_id,
        candidate_number=candidate_number,
        action_type=action.action_type,
        subject=action.subject,
        enabled=action.direction,
        a_dependency_of=_whose_dependency_was_acted_on(action, alerting_service),
        accelerator=action.pinned_to,
        at=now()
    )
    publish(announcement, publisher)
    announced.append(announcement)


def _the_put_back_is_owed(owe_a_put_back: OweAPutBack,
                          because: str,
                          *,
                          incident_id: str,
                          hypothesis_id: str) -> None:
    """Puts on the claim that its change was refuted and is owed back, with what
    the wait found - before the put-back is attempted.

    A write that fails is logged and the attempt goes on, for
    `_the_change_was_made`'s reason: the put-back is what the refutation is
    owed, and the completion writes the verdict whatever the early copy did -
    abandoning the attempt over a record would leave a refuted change standing.
    All but a write refused for a lost run: the walk no longer holds its run,
    and a put-back from here would be nobody's walk changing production.
    """
    try:
        owe_a_put_back(incident_id, hypothesis_id=hypothesis_id, because=because)
    except Exception as error:
        if was_lost(error):
            raise

        logger.warning("the put-back could not be recorded as owed before it was attempted",
                       exc_info=True,
                       extra={"incident_id": incident_id, "hypothesis_id": hypothesis_id})


@dataclass(frozen=True)
class _Resumption:
    """What a walk refused the claim carries into picking the earlier attempt
    up: the policy's answer for the action, this walk's own plan or the
    refusal of it, and every collaborator the node was handed that a resumed
    attempt can reach.

    The answer is an admission or a refusal, and it is asked for only where the
    action would be taken anew (`_the_claim_taken`). Everything else a resumed
    walk does - reading whether the change was made, watching one that was,
    putting back one owed back - is about a change already made, and goes on
    whichever it is. A walk the policy refused has no plan of its own: a plan
    is the first step of a new write, and none follows."""

    admission: Admitted[Action] | Refusal
    planned: Planned[Any] | None
    refused: Outcome | None
    resuming: Resuming
    take: TakeAction
    complete_action: CompleteAction
    advance_action: AdvanceAction
    owe_a_put_back: OweAPutBack
    record_outcome: RecordOutcome
    still_wanted: IsStillWanted
    acting_for: ActingFor
    publisher: Publisher
    now: Callable[[], datetime]


def _the_earlier_attempt_resumed(state: IncidentState,
                                 claimed: ClaimedAction | None,
                                 resumption: _Resumption) -> StateDelta:
    """What a walk resumed inside the mitigation node answers with, picking the
    earlier attempt up at the step its row records (spec §11.1).

    An outcome on file means the earlier attempt finished: this walk reports
    the ending it brought the walk to, if any, and lets the routing continue as
    though it had reached it - the ending the walk that recorded it reported,
    from the same verdict, rather than a reading of its own. An outcome nobody
    here can read escalates without asking anything: a verdict was reached, and
    every answer available would be wrong.

    No outcome means the worker died mid-action, and the claim's progress says
    how far it got - each step asked of the estate rather than taken on either
    walk's memory, since the estate is the only record of what a process that
    no longer exists managed to do. Only claimed, the change is asked after
    (`_the_claim_resumed`); told as made, it is asked whether it still stands
    and watched (`_the_change_made_resumed`); owed back, it is put back
    (`_the_put_back_resumed`). Told as unknown, an earlier resume already failed
    to find out, and the incident escalates on that - asking again could only
    be read as licence to act a second time on a change somebody may already
    have made.
    """
    assert state.cursor.hypothesis is not None and state.action is not None

    outcome = claimed.outcome if claimed is not None else None

    if isinstance(outcome, UnreadVerdict):
        return _the_resumed_walk_stops(
            f"an earlier attempt already acted on this explanation, and recorded an "
            f"outcome this version cannot read: {outcome}"
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
                hypothesis_id=state.cursor.hypothesis.id,
                outcome=outcome
            ),
            resumption.publisher
        )

        return StateDelta(
            ending=_the_ending_reached(outcome),
            # Told outright: the claim records the verdict and not the reason,
            # and left unset the walk would keep an earlier round's reason and
            # hand it on as this action's.
            action_because=None,
            acted_at=_when_it_was_made(claimed),
            narration=Narration(
                action="mitigation resumed",
                detail=f"an earlier attempt already acted on this explanation: "
                       f"{outcome}"
            )
        )

    if claimed is None or claimed.progress is ActionProgress.UNKNOWN:
        return _the_resumed_walk_stops(_A_CHANGE_NOBODY_CAN_ACCOUNT_FOR)

    match claimed.progress:
        case ActionProgress.CLAIMED:
            return _the_claim_resumed(state, claimed, resumption)
        case ActionProgress.PERFORMED:
            return _the_change_made_resumed(state, claimed, resumption)
        case ActionProgress.PUTTING_BACK:
            return _the_put_back_resumed(state, claimed, resumption)
        case _:
            # Not performed with no outcome recorded against it: a row no walk
            # writes, so one nothing here can account for.
            return _the_resumed_walk_stops(_A_CHANGE_NOBODY_CAN_ACCOUNT_FOR)


def _the_claim_resumed(state: IncidentState,
                       claimed: ClaimedAction,
                       resumption: _Resumption) -> StateDelta:
    """A claim and nothing more: the dead worker may or may not have made its
    change, and the estate is asked first - before anybody is asked whether it
    is still wanted, so a change found made is never recorded as one not taken.

    Asked on the plan the claim was written with, the write's own rule without
    the write. A claim written with none - its plan was refused and the worker
    died before recording it - has this walk's own plan, there being no other.
    A restart or a discard has no plan and no record of whether it ran, and is
    never done twice on a guess: it is handed over as nobody can say.

    Made, the row is moved on to made with what the estate says puts it back
    and when, and carried on as a change told as made. Not made, the action is
    taken on the plan as the live walk takes it, its compare guarding the gap -
    and what the read said of the claim's is out there all the same, a
    suspension standing, is recorded as left behind wherever taking it ends
    before its own change. Somebody's change since is the live write's refusal,
    recorded as the live walk records it - where this claim's change had landed
    first, the row is moved on to made at no moment the estate gave, and dated
    by the claim, the nearest it has. Nobody can say is kept on the claim, with
    whatever the refusal carried of the claim's, which is final, and handed
    over with nothing completed.

    A claim written with no plan is taken on this walk's, written onto the claim
    first: the plan lives on the claim, and the write compares with it. A walk
    the autonomy policy refused made no plan, so a claim written with none is
    handed over as nobody can say, as a restart's is - nothing can be asked of
    the estate without a plan, and nothing will be taken.
    """
    assert state.cursor.hypothesis is not None and state.action is not None
    action = state.action.proposed_action
    planned = claimed.planned if claimed.planned is not None else resumption.planned

    if planned is None:
        if resumption.refused is not None:
            # The plan was refused, by the dead worker's walk and by this one:
            # nothing was written, and the refusal is the attempt.
            result = (resumption.refused if resumption.still_wanted(state.incident_id)
                      else stopped_before_it_was_taken())

            return _the_attempt_recorded(state, result, None, resumption.complete_action,
                                         resumption.record_outcome, resumption.publisher)

        _the_claim_is_told(state, resumption.advance_action, ActionProgress.UNKNOWN)

        return _the_resumed_walk_stops(_A_CHANGE_NOBODY_CAN_ACCOUNT_FOR)

    if claimed.planned is None:
        _the_plan_is_put_on_the_claim(state, planned, resumption)

    with resumption.acting_for(claimed.action_id):
        answer = resumption.resuming.whether_it_was_made(
            action, planned,
            change_made=partial(_the_change_was_found_made, resumption, claimed, state=state)
        )

        if isinstance(answer, NobodyCanSay):
            _the_claim_is_told(state, resumption.advance_action, ActionProgress.UNKNOWN,
                               undo_descriptor=answer.left_behind)

            return _the_resumed_walk_stops(_A_CHANGE_NOBODY_CAN_ACCOUNT_FOR)

        if isinstance(answer, Outcome):
            # Rule 6: a change made - this claim's, landed before somebody
            # overtook it - is dated by the claim, the estate giving no moment.
            return _the_attempt_recorded(state, answer,
                                         claimed.claimed_at if answer.performed else None,
                                         resumption.complete_action,
                                         resumption.record_outcome, resumption.publisher)

        if isinstance(answer, Made):
            return _the_found_made_carried_on(state, claimed, answer, resumption)

        return _the_claim_taken(state, claimed, planned, answer, resumption)


def _the_found_made_carried_on(state: IncidentState,
                               claimed: ClaimedAction,
                               made: Made[Any],
                               resumption: _Resumption) -> StateDelta:
    """A claimed change found made: moved on to made, dated by when the estate
    says it was - the only record of when it happened, and no moment at all
    where the estate has none, never this walk's clock - then announced where
    nothing is on file, and watched as a change told as made is, from its
    claim: when the estate says it was made is when it was said, and can be a
    minute after the service acted."""
    assert state.cursor.hypothesis is not None and state.action is not None

    _the_claim_is_told(state, resumption.advance_action, ActionProgress.PERFORMED,
                       undo_descriptor=made.descriptor, performed_at=made.made_at)
    acted_at = made.made_at if made.made_at is not None else claimed.claimed_at
    _announced_where_none_is_on_file(state, acted_at, resumption)

    return _the_change_watched(state, made.descriptor, acted_at, claimed.claimed_at,
                               resumption)


def _the_claim_taken(state: IncidentState,
                     claimed: ClaimedAction,
                     planned: Planned[Any],
                     not_made: NotMade[Any],
                     resumption: _Resumption) -> StateDelta:
    """A claimed change found not made, taken on its plan as the live walk takes
    it, and dated from its claim as the live walk dates it - unless the autonomy
    policy now refuses it, when it is a new write nobody admitted
    (`_the_retake_refused`), or the metrics can no longer judge it, when a
    change nobody can judge is not made. Either way, what the read said of the
    claim's is out there all the same is recorded as left behind where the
    attempt ends before its own change, and known: nothing else of the claim's
    was made."""
    assert state.cursor.hypothesis is not None and state.action is not None
    left_behind = not_made.left_behind

    if isinstance(resumption.admission, Refusal):
        return _the_retake_refused(state, resumption.admission, left_behind, resumption)

    if not _the_metrics_reach_back(state, resumption):
        _the_attempt_recorded(
            state,
            Outcome(verdict=Verdict.ESCALATED, detail=_THE_METRICS_NO_LONGER_REACH_BACK,
                    undo_descriptor=left_behind, left_behind_known=True, judged=False,
                    performed=False),
            None, resumption.complete_action, resumption.record_outcome,
            resumption.publisher
        )

        return _the_resumed_walk_stops(_THE_METRICS_NO_LONGER_REACH_BACK)

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION),
            resumption.publisher)
    announced: list[ActionTaken] = []

    try:
        # Dated from the claim, as the live walk dates it: it was written before
        # this write as it was before the one that was lost.
        result = _taken(state, resumption.take, resumption.admission, planned,
                        claimed.claimed_at, resumption.still_wanted, resumption.advance_action,
                        resumption.owe_a_put_back, announced, resumption.publisher,
                        resumption.now)
    except LostAfterSending:
        # As the live walk handles it: nobody can say whether it was carried out.
        logger.warning("the action was asked for and its answer was lost",
                       exc_info=True, extra={"incident_id": state.incident_id})

        return _nobody_can_say_whether_it_was_carried_out(state, resumption.advance_action,
                                                          planned)

    if not result.performed and result.undo_descriptor is None and left_behind is not None:
        result = result.model_copy(update={"undo_descriptor": left_behind})

    return _the_attempt_recorded(state, result, announced[0].at if announced else None,
                                 resumption.complete_action, resumption.record_outcome,
                                 resumption.publisher)


def _the_retake_refused(state: IncidentState,
                        refusal: Refusal,
                        left_behind: UndoDescriptor | None,
                        resumption: _Resumption) -> StateDelta:
    """A claimed change found not made, on a walk the autonomy policy now
    refuses: not taken, and the incident handed to a person.

    Taking it now would be a new write, and nothing admitted it - the declared
    set or the register narrowed while the walk was down. The claim is
    completed rather than left open, as a tier's refusal of the write completes
    it: not performed, with the refusal's sentence as the reason, and what the
    read said of the claim's is out there all the same as left behind - known,
    since nothing else of it was made. An open claim would keep its subject
    closed to every incident after this one for a change nobody made.
    """
    assert state.cursor.hypothesis is not None and state.action is not None

    because = why_it_was_refused(refusal)
    logger.warning("a claimed action not admitted when it came to be taken again",
                   extra={"refusal": refusal,
                          "action_type": state.action.proposed_action.action_type,
                          "subject": state.action.proposed_action.subject})
    _the_attempt_recorded(
        state,
        Outcome(verdict=Verdict.ESCALATED, detail=because, undo_descriptor=left_behind,
                left_behind_known=True, judged=False, performed=False,
                not_performed_because=because),
        None, resumption.complete_action, resumption.record_outcome, resumption.publisher
    )

    return _the_resumed_walk_stops(because)


def _the_change_made_resumed(state: IncidentState,
                             claimed: ClaimedAction,
                             resumption: _Resumption) -> StateDelta:
    """A change told as made: the worker died in the wait. Asked whether it is
    still as it was left, and watched afresh where it is - in the words it was
    made with, and not made again.

    Somebody's change since is handed over saying what was found, the row
    keeping the way back it already holds so a withdrawal can put back
    whatever of it is Argus's; and so is a change nobody can say still stands,
    since a reading of a service whose state nobody can describe would judge a
    change nobody can say is there - a read that failed among it. A row that
    says the change was made and keeps nothing that puts it back has nothing to
    ask after, and is handed over as a change made and never recorded.

    Whichever the answer, the change was made, so it is announced where the
    dead worker died before announcing it, dated when it was made.
    """
    assert state.cursor.hypothesis is not None
    descriptor = claimed.undo_descriptor

    if descriptor is None:
        return _the_resumed_walk_stops(_A_CHANGE_MADE_AND_NEVER_RECORDED)

    with resumption.acting_for(claimed.action_id):
        found = _whether_it_still_stands(state, claimed.planned, descriptor, resumption)
        acted_at = _when_it_was_made(claimed)
        _announced_where_none_is_on_file(state, acted_at, resumption)

        if found.still_argus_s is not True:
            return _the_resumed_walk_stops(_said_with_what_was_found(
                _CHANGED_SINCE_IT_WAS_MADE if found.still_argus_s is False
                else _NOBODY_CAN_SAY_IT_STILL_STANDS,
                found.found
            ))

        return _the_change_watched(state, descriptor, acted_at, claimed.claimed_at,
                                   resumption)


def _whether_it_still_stands(state: IncidentState,
                             planned: Planned[Any] | None,
                             descriptor: UndoDescriptor,
                             resumption: _Resumption) -> ChangeFound:
    """The estate's answer to whether a change made is still as Argus left it -
    or, where the read itself failed, nobody can say, in its own words. A lost
    run raises: the incident is another claim's walk."""
    try:
        return resumption.resuming.still_argus_s(planned, descriptor)
    except Exception as error:
        if was_lost(error):
            raise

        logger.warning("whether a resumed change still stands could not be read",
                       exc_info=True, extra={"incident_id": state.incident_id})

        return ChangeFound(still_argus_s=None, found=str(error) or type(error).__name__)


def _the_change_watched(state: IncidentState,
                        descriptor: UndoDescriptor,
                        acted_at: datetime | None,
                        acted_from: datetime,
                        resumption: _Resumption) -> StateDelta:
    """A change an earlier worker made, watched as the live walk watches it and
    recorded as the live walk records it - unless the metrics no longer reach
    back to when the incident began, when whether it helped cannot be judged
    and it is handed over, still standing, rather than watched.

    `acted_at` is when it was made, for the record; `acted_from` is what the
    watch dates the action from - the claim, written before the write was sent,
    as the live walk dates it.

    Acted for the claim's own row by whoever calls it, so a refutation the
    watch puts back is a write marked as that action's.
    """
    assert state.cursor.hypothesis is not None and state.action is not None

    if not _the_metrics_reach_back(state, resumption):
        return _the_resumed_walk_stops(_THE_METRICS_NO_LONGER_REACH_BACK)

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION),
            resumption.publisher)
    result = resumption.resuming.watch(
        state.action.proposed_action,
        performed_as_recorded(state.action.proposed_action, descriptor),
        acted_from=acted_from,
        **_what_the_wait_is_handed(state, resumption.still_wanted, resumption.publisher),
        put_back_owed=partial(
            _the_put_back_is_owed,
            resumption.owe_a_put_back,
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id
        )
    )

    return _the_attempt_recorded(state, result, acted_at, resumption.complete_action,
                                 resumption.record_outcome, resumption.publisher)


def _the_put_back_resumed(state: IncidentState,
                          claimed: ClaimedAction,
                          resumption: _Resumption) -> StateDelta:
    """A change owed back: the watch refuted it and the worker died before
    putting it back. Put back for what the watch found - not watched again, not
    made again - said in the words the walk that made it used, and recorded as
    the live walk records its put-back. The row already says it is owed back,
    so it is neither owed again nor moved on."""
    assert state.cursor.hypothesis is not None and state.action is not None
    descriptor, because = claimed.undo_descriptor, claimed.put_back_because

    if descriptor is None or because is None:
        return _the_resumed_walk_stops(_A_CHANGE_MADE_AND_NEVER_RECORDED)

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION),
            resumption.publisher)

    with resumption.acting_for(claimed.action_id):
        result = resumption.resuming.settle(
            state.action.proposed_action.action_type,
            performed_as_recorded(state.action.proposed_action, descriptor),
            because,
            still_wanted=partial(resumption.still_wanted, state.incident_id)
        )

    return _the_attempt_recorded(state, result, _when_it_was_made(claimed),
                                 resumption.complete_action, resumption.record_outcome,
                                 resumption.publisher)


def _the_change_was_found_made(resumption: _Resumption,
                               claimed: ClaimedAction,
                               undo_descriptor: UndoDescriptor | None,
                               *,
                               state: IncidentState) -> None:
    """What a resumed read's refusal says of a change that landed before
    somebody overtook it: put on the claim as made, with what puts it back - at
    no moment, since the refusal gives none and this walk's clock would date it
    minutes after it happened - and announced where no line for the claim is
    on file, dated by the claim, the nearest moment the row has."""
    _the_claim_is_told(state, resumption.advance_action, ActionProgress.PERFORMED,
                       undo_descriptor=undo_descriptor, performed_at=None)
    _announced_where_none_is_on_file(state, claimed.claimed_at, resumption)


def _the_plan_is_put_on_the_claim(state: IncidentState,
                                  planned: Planned[Any],
                                  resumption: _Resumption) -> None:
    """Writes the plan this walk takes a claim's action on onto a claim written
    with none, before the write - so a walk resumed after this one dies asks
    after the change on the plan it was taken on.

    A write that fails raises, and the change is not made: a write made with
    the plan nowhere on the claim leaves a walk resumed after this one to plan
    again - a flag's plan then refused as spent, and a change that landed read
    as never attempted. The live walk never writes without its claim carrying
    the plan, and nothing is made yet, so the run's failure costs only its
    escalation.
    """
    assert state.cursor.hypothesis is not None

    resumption.resuming.plan_the_claim(state.incident_id,
                                       hypothesis_id=state.cursor.hypothesis.id, planned=planned)


def _the_claim_is_told(state: IncidentState,
                       advance_action: AdvanceAction,
                       to: ActionProgress,
                       *,
                       undo_descriptor: UndoDescriptor | None = None,
                       performed_at: datetime | None = None) -> None:
    """Moves the claim on to what a resumed walk learnt of it, so the next walk
    to find it reads the answer rather than asking again.

    Made is told with when the estate says it was made, and told outright -
    `None` included - so a change the estate dates nowhere is never dated by
    this walk's clock. A write that fails is logged and the walk goes on, for
    `_the_change_was_made`'s reason; all but a write refused for a lost run.
    """
    assert state.cursor.hypothesis is not None

    try:
        if to is ActionProgress.PERFORMED:
            advance_action(state.incident_id, hypothesis_id=state.cursor.hypothesis.id, to=to,
                           undo_descriptor=undo_descriptor, performed_at=performed_at)
        else:
            advance_action(state.incident_id, hypothesis_id=state.cursor.hypothesis.id, to=to,
                           undo_descriptor=undo_descriptor)
    except Exception as error:
        if was_lost(error):
            raise

        logger.warning("a resumed claim could not be moved on", exc_info=True,
                       extra={"incident_id": state.incident_id, "to": to})


def _announced_where_none_is_on_file(state: IncidentState,
                                     at: datetime | None,
                                     resumption: _Resumption) -> None:
    """The line saying the action was taken, dated when the change was made -
    where the dead worker died before announcing it. It announced whether or
    not its own advance landed, so a line can be on file for a claim with
    nothing after it; two would read as Argus acting twice."""
    assert state.cursor.hypothesis is not None and state.action is not None

    if at is None or resumption.resuming.announced(state.incident_id, state.cursor.hypothesis.id):
        return

    action = state.action.proposed_action
    publish(
        ActionTaken(
            incident_id=state.incident_id,
            hypothesis_id=state.cursor.hypothesis.id,
            candidate_number=state.cursor.hypothesis.number,
            action_type=action.action_type,
            subject=action.subject,
            enabled=action.direction,
            a_dependency_of=_whose_dependency_was_acted_on(action, state.alert.service),
            accelerator=action.pinned_to,
            at=at
        ),
        resumption.publisher
    )


def _when_it_was_made(claimed: ClaimedAction) -> datetime | None:
    """When the row says its change was made, for the round that remembers the
    attempt: the moment it was made where the row keeps one, the claim's -
    written just before the change - for a change made at no recorded moment,
    and nothing for a change never made, as the live walk tells it."""
    if claimed.progress.its_change_was_made() is not True:
        return None

    return claimed.performed_at if claimed.performed_at is not None else claimed.claimed_at


def _when_the_incident_began(state: IncidentState) -> datetime | None:
    """The instant the incident began: the investigation's minute, else the
    one the alert stated, else when the alert fired - `None` where nothing
    states one."""
    if state.history.onset is not None:
        return parse_iso(state.history.onset.minute)

    return state.alert.stated_onset if state.alert.stated_onset is not None \
        else state.alert.started_at


def _the_metrics_reach_back(state: IncidentState, resumption: _Resumption) -> bool:
    """Whether the metrics kept still reach back to when the incident began -
    the oldest minute kept included - so a change watched now can be judged
    against the service as it was before. An incident nothing dates is watched,
    as the live walk watches it: no window can be said to have passed it."""
    began = _when_the_incident_began(state)

    return began is None or resumption.now() - began <= resumption.resuming.metrics_window


def _said_with_what_was_found(said: str, found: str | None) -> str:
    """`said`, and what the estate's read found where it said anything."""
    return said if found is None else f"{said}: {found}"


def _the_resumed_walk_stops(why: str) -> StateDelta:
    """The incident handed to a person by a resumed walk that cannot carry the
    earlier attempt on, saying `why` in the words a person reads.

    Said as the walk's ending, escalated, and not as a status: the status is
    `status_after`'s to draw from the ending, and the wrapper's to write with
    the sentence that accounts for it."""
    return StateDelta(
        ending=Escalated(),
        narration=Narration(action="mitigation resumed", detail=why)
    )


def _nothing_to_act_on() -> StateDelta:
    """The unreachable case, handled rather than assumed away.

    The gate escalates an unproposed action, so nothing should arrive here
    without one. A node that indexed into `None` on the day that stopped being
    true would fail inside a state-changing step, which is the worst place to
    discover it.
    """
    return StateDelta(
        ending=Escalated(),
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

    An `escalated` outcome still ends things immediately: nothing was measured,
    or nothing can be - a change whose answer was lost may stand, and a resumed
    claim nobody can account for may too - so a further experiment would run
    against a world Argus cannot describe.
    """
    if state.status == IncidentStatus.MITIGATED:
        return FIXING_ROUTE
    if state.status == IncidentStatus.MITIGATING:
        return NEXT_CANDIDATE_ROUTE
    return ESCALATED_ROUTE
