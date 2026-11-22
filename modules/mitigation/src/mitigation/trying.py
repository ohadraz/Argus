"""Taking one proposed action, and judging what the service did (spec §7.3).

The mutating half of the Mitigator. `actions.py` decides what to do without
touching anything; this performs it, runs the verification wait, and puts the
change back where the wait refutes the hypothesis it was taken on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, NamedTuple, Protocol, assert_never

from core import sleep_on_the_clock, to_iso_minute, utc_now, was_lost
from core.anomaly import (
    AnomalyThresholds,
    find_recovery,
    has_a_departure_in_it,
    has_a_reading_since,
    has_recovered_since,
    minutes_a_recovery_must_hold,
)
from core.autonomy import Admitted
from core.budget import StillWanted, wanted_throughout
from core.events import (
    AwaitingRecovery,
    Publisher,
    RecoveryChecked,
    RetrievalUnanswered,
    nobody,
    publish,
)
from core.models import (
    ActionType,
    AlertRuleStanding,
    Made,
    MetricBucket,
    NotMade,
    Planned,
    UndoDescriptor,
    changes_something_persistent,
    the_kind,
)
from mcp_transport import (
    CHANGED_SINCE_MARKER,
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_KNOWN_MARKER,
    PERFORMED_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    ActionExhausted,
    ChangedSince,
    LostAfterSending,
    McpToolError,
    PlatformUnreachable,
    without_the_payload,
)

from mitigation.actions import (
    Action,
    Outcome,
    UndoAttempt,
    Undone,
    Verdict,
)
from mitigation.kinds import (
    KindOf,
    Performed,
    UndoingKindOf,
    kind_of,
    kind_planning,
    kind_undoing,
)
from mitigation.tools import (
    Arrival,
    ArrivalFor,
    Clock,
    HasArrived,
    MetricsFetcher,
    MitigationSettings,
    PerformingWrites,
    RuleReader,
    Sleeper,
    nothing_to_wait_for,
)

__all__ = ["ChangeMade", "NobodyCanSay", "PutBackOwed", "UndoChange", "plan_action",
           "settle_the_refutation", "stopped_before_it_was_taken", "take_action",
           "watch_what_was_performed", "whether_it_was_made"]

# Told that the action's change was made, with what the tier said would put it
# back - `None` for a change that leaves nothing to restore. Called once, the
# moment the tier answers and before the wait, so a caller can record the
# change while the worker that made it is still alive to say so: the wait is
# the longest stretch of an attempt, and the one a worker is likeliest to die
# in.
type ChangeMade = Callable[[UndoDescriptor | None], None]

# Told that the watch refuted a change that left something to put back, with
# what the watch found - before the put-back is attempted, so a caller can
# record the change as owed back while the worker that owes it is still alive
# to say so. Not told for a refutation with nothing to put back, nor for any
# other verdict.
type PutBackOwed = Callable[[str], None]

# What a refuted change says of its put-back where a person ended the incident
# after the watch refuted it and before it could be put back.
_NOT_PUT_BACK = "was not put back: a person ended the incident before it could be"

# How often the service is re-read while waiting for it to answer an action.
# Metrics are aggregated per minute, so a tighter interval only re-reads the
# same four numbers; a looser one spends the verification budget waiting.
_SECONDS_BETWEEN_METRIC_READS = 10.0

logger = logging.getLogger(__name__)


class UndoChange(Protocol):
    """Puts one recorded change back and says what became of it.

    Declared here rather than beside `undo_change` because it is this module's
    requirement, not that one's promise: what taking an action needs is
    something that puts a change back, and `undo_change` happens to be the
    thing that does. A test supplying its own gets to say so in a type.
    """

    def __call__(self, undo_descriptor: UndoDescriptor, /) -> UndoAttempt:
        ...

    # The descriptor and nothing else. Whoever supplies the undo binds every
    # collaborator into it - the provider check, because that check needs the
    # configuration this module is handed rather than the one it used to read,
    # and the writes, because a rollback's undo needs one this module has no
    # business holding and a caller passing only the flag setter would bind an
    # undo that works for one kind of change and raises on the other.
    #
    # It is also what lets one binding serve both callers. A withdrawal puts
    # back every change an incident made and holds no setter of its own, so a
    # protocol demanding one here would make the walk's undo and the worker's
    # two different things again.


def _nobody_told(undo_descriptor: UndoDescriptor | None) -> None:
    """A change made with nobody to tell, for a caller recording nothing."""


def _nobody_owed(because: str) -> None:
    """A put-back owed with nobody to tell, for a caller recording nothing."""


def take_action(admitted: Admitted[Action],
                settings: MitigationSettings,
                thresholds: AnomalyThresholds,
                fetch_metrics: MetricsFetcher,
                now: Clock = utc_now,
                sleep: Sleeper = sleep_on_the_clock,
                still_wanted: StillWanted = wanted_throughout,
                arrivals: ArrivalFor = nothing_to_wait_for,
                incident_id: str | None = None,
                publisher: Publisher = nobody,
                *,
                onset: datetime | None = None,
                incident_began: str | None = None,
                rule: str | None = None,
                read_rule: RuleReader | None = None,
                plan: Planned[Any] | None,
                acted_from: datetime,
                writes: PerformingWrites,
                undo: UndoChange,
                change_made: ChangeMade = _nobody_told,
                put_back_owed: PutBackOwed = _nobody_owed,
                kinds: KindOf = kind_of,
                undoing_kinds: UndoingKindOf = kind_undoing) -> Outcome:
    """Performs the admitted action and answers with what the service then did
    (spec §7.3).

    `admitted` rather than an action, and that is the whole of §13's gate as far
    as this function is concerned. Only `core.autonomy.admit` builds one, so an
    action reaching the write here was put to the declared set and to the
    estate's register first - by whoever called, however they came to call. A
    bare `Action` does not type-check, and an `Admitted` nobody admitted cannot
    be built.

    `rule` is the alert rule that paged, where the alert is about a series and
    named one, and `read_rule` is how its standing is read. Given both, the
    verdict is the rule's: it defines what is acceptable for the service, so the
    action holds when the rule stops firing and fails when it is still firing
    at the deadline the rule itself sets. The metrics are then read only to date
    the recovery. Without them the levels decide.

    Four things happen in order, and the order is the point. The action is
    performed, which is the only moment production state changes. The change is
    waited for, because a platform that has accepted one is not a service that is
    serving it. The service is then re-read until a minute that began *after* the
    change was in force can be judged - the newest bucket covers the minute in
    progress, aggregated over seconds that are mostly pre-change, so a verdict
    read off it describes the incident rather than the mitigation. And a refuted
    action is put back, where there is anything to put back.

    Which action is performed is the only thing that differs between kinds. The
    waiting and the judging are identical, and deliberately so: a restart and a
    flag revert are answered by the same question - did the service return to
    its baseline - asked of the same numbers by the same rule.

    The verdict rests on the same departure rule that located the onset, so
    Mitigation and the Investigator cannot disagree about whether a given
    minute was healthy - two parts of Argus that could would be two incidents.

    An action that could not be taken at all is never `REFUTED`: nothing was
    changed, so there is nothing to judge and nothing to undo, and a verdict here
    would describe an experiment that never ran. Which of the other two it is
    depends on *why* it could not be taken, and the difference decides whether the
    walk goes on. A tier that could not be reached, or that refused after it had
    already changed something, is `ESCALATED` - nobody can say what state
    production is in. A tier that answered and said the action has nowhere left to
    go is `NOT_ATTEMPTED`, and the walk moves to its next candidate: a bound Argus
    holds is not a reason to wake somebody.

    A write sent and never answered, which the transport would not ask again
    (`LostAfterSending`), is none of these: nothing can say whether the change
    was made, and every verdict says something about it. It is raised, before
    anything is told as made, for the walk to record that nobody can say.

    `incident_began` is the minute the investigation dated the incident from, and
    is what the recovery is dated after - not to be confused with `onset`, which
    is a minute the *alert* stated and answers whether the incident's minutes
    were ever published. A recovery found by re-reading where the incident began
    from the window being polled can be the end of an earlier episode of a
    service that flaps, which would date this incident's end before its start.

    `incident_id` is optional because an `Action` is not incident-scoped and
    neither is this call - a caller with no incident to attribute the wait to
    narrates nothing, which is better than an event hung on an incident that
    was invented to hold it.

    `writes` are the writes that *perform* an action, one per kind, and `undo` is
    what puts one back. Two collaborations rather than one list, because they
    happen at different moments and because the alternative grew by a parameter
    per action kind: the restorers and the check that guards them live on
    `PuttingBack`, which `putting_back_over` builds and `an_undo_over` binds into
    `undo_change`.

    `undo` is required. It used to be optional, composed here from a flag setter
    and a restorer when a caller supplied none - and no caller ever did: the
    Orchestrator has always passed the binding its withdrawal path shares. What
    the default bought was three parameters on this signature that production
    never read, and a second assembly of an undo for a test to exercise instead
    of the one that runs.

    Asked once more whether anybody still wants it, immediately before the
    write. The walk asked before its step began, and between that and here sit
    a claim, two publishes and on a resumed run a provider read - long enough
    for a person to have said stop. Applying it anyway would change the world
    after they did, and leave behind something for the withdrawal to put back.

    `change_made` is told once the write has landed, before the wait, with the
    descriptor the tier returned. Never on any of the four ways an attempt ends
    before its write: nothing was made, and told otherwise a caller records a
    candidate as tried that never was. What a caller does with it is the
    caller's - this does not guard it, since whether a failure to record may
    be survived is the recorder's judgement and not the Mitigator's.

    `put_back_owed` is told once the wait has refuted a change that left
    something to put back, with what the wait found, before the put-back - see
    `watch_what_was_performed`, which is this from the moment the write landed.
    Unguarded for `change_made`'s reason.

    `plan` is the change `plan_action` worked out and the claim carries, which
    the write compares the estate with before it changes anything - `None` for
    an action with nothing to plan, a restart or a discard. Required, `None`
    included, because an action taken on a plan nobody chose would be compared
    against a state nothing wrote down. A write that finds somebody else has
    changed the service since the plan escalates without a verdict: somebody is
    acting on it now, and Argus hands it to a person rather than act beside
    them. Where this claim's own change had landed before they did - an earlier
    asking whose answer was lost - it was performed, and is told as made, but
    neither watched nor put back: what the service does now is no longer
    Argus's change alone to answer for.

    `acted_from` is when the action's claim was written - after the plan's read
    and before the write, so the latest moment known to come before the write
    was sent, on the walk's own clock as the arrival and the deadlines are - and
    is where the minutes asked whether the incident was ever watched end. Not the
    moment the write answered: the call can straddle a minute, and a service
    that restores its rows from its own minute of the change would have them
    counted as before it. Required, because a caller that forgot it would have
    the answer's moment stand in for it, and a blind spot refuted by the very
    rows it brought back.

    `kinds` says which kind an action is, and so whose write performs it and
    whose words describe it; `undoing_kinds` says the same of a change that was
    put back, for the words that end the sentence. Both default to the one
    answer production has, and are here so that a case can say what a kind did
    without performing it.
    """
    # The type says so already; this says so to a caller nothing type-checked,
    # before anything is written.
    if not isinstance(admitted, Admitted):
        raise TypeError("only an admitted action is taken - ask core.autonomy.admit")

    action = admitted.action

    if not still_wanted():
        logger.info("action not taken, incident no longer wanted")

        return stopped_before_it_was_taken()

    kind = kinds(action)

    try:
        performed = kind.perform(action, plan, writes)
    except ChangedSince as changed:
        # Before the handler below, for the reason the exhausted action is
        # caught first there: this is an `McpToolError` too.
        #
        # Told as made where this claim's own change had landed, and only
        # there - the tier says so outright rather than leaving it to be read
        # off what it carries, since a suspension alone is not the change.
        if changed.performed:
            change_made(changed.undo_descriptor)

        return _changed_since(changed, kind.intent(action))
    except LostAfterSending:
        # Before the broad case, which would read it as a write that failed and
        # so as nothing performed. Nothing can say whether the change was made,
        # and every verdict says something about it: the walk is told, and
        # records the claim as nobody can say.
        raise
    except Exception as error:
        return _not_performed(error, kind.intent(action), action.action_type,
                              could_have_written=True)

    # Outside the `try` above, so a caller's failure to record is never read as
    # the action's failure to happen - the change is made by now.
    change_made(performed.undo_descriptor)

    return watch_what_was_performed(
        action, performed, settings, thresholds, fetch_metrics, now, sleep, still_wanted,
        arrivals, incident_id, publisher, onset=onset, acted_from=acted_from,
        incident_began=incident_began, rule=rule, read_rule=read_rule, undo=undo,
        put_back_owed=put_back_owed, undoing_kinds=undoing_kinds
    )


def watch_what_was_performed(action: Action,
                             performed: Performed,
                             settings: MitigationSettings,
                             thresholds: AnomalyThresholds,
                             fetch_metrics: MetricsFetcher,
                             now: Clock = utc_now,
                             sleep: Sleeper = sleep_on_the_clock,
                             still_wanted: StillWanted = wanted_throughout,
                             arrivals: ArrivalFor = nothing_to_wait_for,
                             incident_id: str | None = None,
                             publisher: Publisher = nobody,
                             *,
                             onset: datetime | None = None,
                             acted_from: datetime,
                             incident_began: str | None = None,
                             rule: str | None = None,
                             read_rule: RuleReader | None = None,
                             undo: UndoChange,
                             put_back_owed: PutBackOwed = _nobody_owed,
                             undoing_kinds: UndoingKindOf = kind_undoing) -> Outcome:
    """Watches a change already made, judges it, and puts it back where the
    watch refutes it - `take_action` from the moment its write has landed.

    Its own entry point because a change can be made by one walk and watched by
    another: a walk resumed after the one that made it died holds the change,
    and making it again would be a second write. Every parameter is
    `take_action`'s, said there; `performed` is what the write produced.
    `acted_from` matters most here: a resumed walk begins watching minutes after
    the write, so the moment it begins is no date for the action at all.

    A refutation that left something to put back is told to `put_back_owed`
    with what the watch found, *before* anything else is done about it, so a
    worker that dies putting it back leaves a record saying the change is owed
    back and why. Then `settle_the_refutation` puts it back. A refutation that
    left nothing to put back - a restart, a discard - owes nobody anything and
    is said as such, with no question asked.
    """
    settled = _what_watching_the_service_settled(
        # Read for the rule that paged, so the recovery is dated on its series.
        partial(fetch_metrics, rule=rule), arrivals(action), now, sleep, still_wanted, settings,
        thresholds, action.action_type, acted_from, incident_id, publisher, onset,
        read_the_rule=(
            partial(read_rule, rule)
            if rule is not None and read_rule is not None
            else None
        ),
        incident_began=incident_began
    )

    if settled.verdict is Verdict.CONFIRMED:
        return Outcome(
            verdict=Verdict.CONFIRMED,
            left_behind_known=True,
            because=settled.because,
            # The reason the watching gave, rather than a sentence written here.
            # One verdict is reached four ways that mean different things - a
            # rule that stopped firing, a level that came down, a reading that
            # returned, and an action that reported what it changed - and a
            # detail hardcoding any one of them would
            # say a service returned to a baseline it may never have left. That
            # is also the whole of the record of *which* rule settled it: the
            # sentence lands in `detail`, where every reader of the incident
            # meets it.
            detail=f"{performed.said} and {settled.because}",
            undo_descriptor=performed.undo_descriptor,
        )

    # Left where it is too, and for a reason of its own: nothing was measured,
    # so there is nothing to act on. Putting the change back is what a
    # refutation does, and doing it on no reading at all would reverse a
    # mitigation that may well have worked - which is the shape this was
    # actually seen in, a shop that had recovered while the tier that would have
    # shown it was timing out. The undo goes with it, because what to do about a
    # service nobody could read is a person's to decide.
    if settled.verdict is Verdict.ESCALATED:
        return Outcome(
            verdict=Verdict.ESCALATED,
            left_behind_known=True,
            detail=f"{performed.said}, and {settled.because}",
            undo_descriptor=performed.undo_descriptor,
            # Said rather than left to the verdict, which is the same word here
            # as it is for a refutation whose undo failed. What reads this is
            # the candidate's row: a hypothesis marked tested by a wait that
            # took no reading is one a later incident is taught to try last.
            judged=False,
        )

    # Left where it is, carrying what would put it back. Undoing it here would
    # be a second opinion about a decision the withdrawal makes once, for every
    # action the incident took and only where nobody else has been in there
    # since Argus wrote.
    if settled.verdict is Verdict.STOPPED:
        return Outcome(
            verdict=Verdict.STOPPED,
            left_behind_known=True,
            detail=f"{performed.said}, and {settled.because}",
            undo_descriptor=performed.undo_descriptor,
            # Nothing was judged here either, whatever the wait read before the
            # stop, and saying so rather than leaving the walk to recognise the
            # word is what lets one fact decide the candidate's row instead of a
            # list of verdicts that has to be kept in step with this one.
            judged=False,
        )

    # Told before anything is done about it, and before anybody is asked
    # whether it is still wanted: a worker that dies from here on leaves a
    # change owed back, said why, rather than one to watch again.
    if performed.undo_descriptor is not None:
        put_back_owed(settled.because)

    return settle_the_refutation(action.action_type, performed, settled.because,
                                 undo=undo, still_wanted=still_wanted,
                                 undoing_kinds=undoing_kinds)


def settle_the_refutation(action_type: ActionType,
                          performed: Performed,
                          because: str,
                          *,
                          undo: UndoChange,
                          still_wanted: StillWanted = wanted_throughout,
                          undoing_kinds: UndoingKindOf = kind_undoing) -> Outcome:
    """Puts back a change the watch refuted, and says what came of it - the
    attempt from the moment its refutation was recorded as owed back.

    Its own entry point because a walk resumed after the one that refuted the
    change died holds a change already judged: it puts it back, and does not
    watch it again. `because` is what the watch found, as the watch said it.

    Asked once more whether anybody still wants it, immediately before the
    put-back - it is a change to the world, and the walk asks before every
    one. Where a person has ended the incident the verdict the watch reached
    stands, refuted and judged, and nothing is put back: the outcome carries
    the change so a withdrawal's unwinding puts it back, and says it was not.
    A refutation with nothing to put back asks nothing, since nothing follows.
    """
    undo_descriptor = performed.undo_descriptor

    if undo_descriptor is not None and not still_wanted():
        logger.info("refuted change not put back, incident no longer wanted")

        return Outcome(
            verdict=Verdict.REFUTED,
            left_behind_known=True,
            because=because,
            # No undo answered, so there is no subject of one to quote: the
            # kind's words for the change already say what it was done to.
            detail=f"{performed.said}, but {because}, and it {_NOT_PUT_BACK}",
            undo_descriptor=undo_descriptor,
            undone=None,
            undone_detail=_NOT_PUT_BACK,
        )

    return _undone(performed, undo, undoing_kinds, action_type, because)


def plan_action(action: Action, *, writes: PerformingWrites) -> Planned[Any] | Outcome | None:
    """The change `action` will make, worked out by the write tier before the
    action is claimed - or, where the tier refused to work it out, the outcome
    the attempt comes to - or `None` for an action with nothing to plan.

    Before the claim, so that the claim carries it from the moment it is
    written: a resumed walk finding the claim compares the estate with the plan,
    and a plan made after the claim leaves a claim with nothing to compare for
    exactly the stretch it is likeliest to be resumed in. A plan changes
    nothing, and nothing here works it out: what the tier answers is what the
    claim records and what the write is handed back.

    A refusal is answered as the outcome of the attempt rather than raised,
    because the refusals that used to come from the write - an action already
    spent, a platform not answering - come from the plan now, and the walk
    records the attempt with them exactly as it did. Whatever stopped a plan, it
    left nothing behind, so the outcome says what it left is known.
    """
    kind = kind_planning(action)

    if kind is None:
        return None

    try:
        return kind.plan(action, writes)
    except Exception as error:
        return _not_performed(error, kind_of(action).intent(action), action.action_type,
                              could_have_written=False)


@dataclass(frozen=True)
class NobodyCanSay:
    """What a read of a claim's change answers where nothing could establish
    whether it was made: `because`, the tier's own words for why, and
    `left_behind`, what the refusal carried of the claim's all the same - a
    suspension a refusal found standing - or `None` where it carried nothing.

    Not "nothing landed", which would have the walk act a second time on a
    change the dead worker may have made; and not an `Outcome`, since this walk
    made no attempt for one to be the outcome of. What it carried is kept on
    the claim, so whatever puts the incident's changes back reaches it.
    """

    because: str
    left_behind: UndoDescriptor | None = None


def whether_it_was_made(action: Action,
                        planned: Planned[Any],
                        *,
                        writes: PerformingWrites,
                        change_made: ChangeMade = _nobody_told,
                        undoing_kinds: UndoingKindOf = kind_undoing
                        ) -> Made[Any] | NotMade[Any] | Outcome | NobodyCanSay:
    """Whether the claim's change on `planned` was made, for a walk resumed
    after the worker that claimed it died - the first question it asks of a
    claimed row, before anything else, so a change found made is never
    recorded as one not taken.

    Made, with when, and not made, with what of the claim's is out there all
    the same, are the tier's answers, and are answered as they came: the walk
    records one as made and carries on, and takes the action on the other as a
    live walk would. Neither is told to `change_made` - a made answer is the
    walk's to record from the answer itself, and told here too it would be
    recorded twice.

    Somebody's change since the plan is the write's own refusal, since the read
    is the write's rule without the write, and is answered as `take_action`
    answers it - the same outcome, and the change told as made where this
    claim's own change had landed. Anything else the read raised is nobody can
    say, in the tier's own words, carrying what the refusal said it left - a
    suspension of the claim's a refusal found standing - and whether that is
    the whole of it is not read: a read that could not tell whether the change
    was made has not said it was not. A lost run raises. Writes nothing.
    """
    try:
        return undoing_kinds(planned.descriptor).whether_it_was_made(action, planned, writes)
    except ChangedSince as changed:
        if changed.performed:
            change_made(changed.undo_descriptor)

        return _changed_since(changed, kind_of(action).intent(action))
    except Exception as error:
        # Every way the read can fail to answer means the same thing to the
        # walk: nobody can say. Narrowing this to the transport's own exception
        # would let a change in the client's vocabulary turn "could not ask" into
        # a crash inside a resumed walk.
        if was_lost(error):
            raise

        logger.warning("whether a claim's change was made could not be read", exc_info=error,
                       extra={"action_type": action.action_type})

        return NobodyCanSay(
            because=(
                _without_the_platform_marker(error) if isinstance(error, PlatformUnreachable)
                else _in_its_own_words(error)
            ),
            left_behind=error.undo_descriptor if isinstance(error, McpToolError) else None
        )


def stopped_before_it_was_taken() -> Outcome:
    """What an attempt comes to where a person ended the incident before the
    action was taken: stopped, with nothing done, judged or left behind.

    One answer for the two places that ask before anything is taken - the last
    question before the write, and the walk's before it records a plan the
    tier refused - so the incident a person ended reads the same whichever of
    the two noticed.
    """
    return Outcome(
        verdict=Verdict.STOPPED,
        left_behind_known=True,
        detail="a person ended the incident before the action was taken",
        undo_descriptor=None,
        judged=False,
        performed=False
    )


def _changed_since(changed: ChangedSince, intent: str) -> Outcome:
    """What an action refused because somebody else has changed the service since
    it was planned comes to: escalated, without a verdict.

    Somebody is acting on the service now, and Argus hands it to a person rather
    than act beside them. Not `NOT_ATTEMPTED`, which would have the walk try its
    next candidate on a service somebody else is changing; and not `REFUTED`,
    since nothing was tested. Nothing was watched, and nothing is put back -
    whatever is out there is no longer Argus's change alone.

    Two records, told apart by whether this claim's own change had landed before
    somebody overtook it, which the tier says outright. Landed, the action was
    performed and the change is carried as made, with what puts it back. Not
    landed, it was not performed - and what it carries is what this claim's
    marks show an earlier asking of it left, a suspension standing, which the
    row this outcome writes is the only record of.
    """
    words = _in_the_words_of_a_change_made_since(changed)

    logger.warning("the service was changed since the action was planned",
                   extra={"performed": changed.performed})

    if changed.performed:
        return Outcome(
            verdict=Verdict.ESCALATED,
            left_behind_known=True,
            detail=f"the change to {intent} landed, and was overtaken since - {words}",
            undo_descriptor=changed.undo_descriptor,
            judged=False,
            performed=True
        )

    return Outcome(
        verdict=Verdict.ESCALATED,
        left_behind_known=True,
        detail=f"did not {intent} - {words}",
        not_performed_because=words,
        undo_descriptor=changed.undo_descriptor,
        judged=False,
        performed=False
    )


def _in_the_words_of_a_change_made_since(changed: ChangedSince) -> str:
    """The refusal's own words, without the tokens that classified it and without
    the descriptor it carried - `_without_the_platform_marker`'s reasoning, for
    the markers a changed-since refusal carries."""
    said = str(changed)

    for marker in (CHANGED_SINCE_MARKER, LEFT_BEHIND_KNOWN_MARKER, PERFORMED_MARKER):
        said = said.replace(marker, "")

    return without_the_payload(said).strip()


def _not_performed(error: Exception,
                   intent: str,
                   action_type: ActionType,
                   *,
                   could_have_written: bool) -> Outcome:
    """What an action that was refused, or failed, before it was performed
    comes to - at its plan or at its write.

    One reading for both, because the refusals are the same refusals: the
    bounds that refused a write refuse its plan now, and the walk reads them
    exactly as it read the write's. What differs is what the failure can have
    left: `could_have_written` is false at a plan, which changes nothing however
    far it got - so what it left is known, and is nothing, whatever the tier
    said or failed to say.

    A lost run raises rather than answering: the incident is another claim's
    walk, and an outcome said here would be said for it.
    """
    # A lost run is not an action that failed: the incident is another claim's
    # walk, and an outcome said here would be said for it.
    if was_lost(error):
        raise error

    if isinstance(error, ActionExhausted):
        # Asked before the broader cases below, and the order is the whole of
        # it: an exhausted action is an `McpToolError` like any other, so a
        # broader case reached first would swallow it into an escalation and
        # this branch would never run.
        #
        # Not `ESCALATED`, because nothing is wrong: the tier was reached, it
        # answered, and its answer is that this action has nowhere left to go - a
        # deployment already at the most replicas Argus may ask for, an
        # autoscaler whose floor already meets its ceiling. Escalating here ends
        # the walk over a bound, and an incident whose next candidate is a flag
        # Argus could revert in seconds reaches a human for no reason.
        #
        # Not `REFUTED` either, which is the trap worth naming: that says the
        # explanation was tested and did not hold, and nothing was tested. A
        # record carrying it would have the postmortem report that the evidence
        # ruled a cause out when nothing ruled it out.
        return Outcome(
            verdict=Verdict.NOT_ATTEMPTED,
            left_behind_known=True,
            detail=f"did not {intent} - {_without_the_marker(error)}",
            not_performed_because=_without_the_marker(error),
            # The same thing the paragraph above says in words, said where the
            # candidate's row can read it: nothing was tested, so nothing about
            # this explanation may be recorded as having been.
            judged=False,
            performed=False
        )

    if isinstance(error, PlatformUnreachable):
        # Asked before the broad case for the reason the exhausted action is:
        # this is an `McpToolError` too.
        #
        # Not `ESCALATED`, because Argus has not run out of moves - it has run
        # out of *this platform's* moves. Five of the seven generic mitigations
        # act through the deployment platform, so a platform that is not
        # answering has taken five away at once and left the other two;
        # escalating here ends a walk whose next candidate is a flag revert on a
        # provider that is still answering.
        #
        # Not `NOT_ATTEMPTED`, which is the distinction worth holding: that says
        # the tier answered and had nowhere left to go - a deployment already at
        # its cap, a floor already at its ceiling - where this says nothing was
        # there to answer. A record carrying it would report a bound that was
        # never reached.
        logger.warning("deployment platform unreachable", extra={"action_type": action_type})

        # Carries what the action left behind, where it left anything. Four of
        # the five actions through the deployment platform suspend its
        # reconciliation before doing what they were asked, so a platform lost
        # after that point leaves an application un-reconciled - and the row
        # this outcome writes is the only record of it. `None` on the ordinary
        # failure, which is the platform going before the first write, and
        # always at a plan.
        return Outcome(
            verdict=Verdict.PLATFORM_UNREACHABLE,
            # Known, as every marked platform failure is: one that may have
            # changed more than it carries is never marked.
            left_behind_known=error.left_behind_known or not could_have_written,
            detail=f"did not {intent} - {_without_the_platform_marker(error)}",
            not_performed_because=_without_the_platform_marker(error),
            undo_descriptor=error.undo_descriptor if could_have_written else None,
            # The action was not taken, so the service was never watched for it.
            # The candidate is passed over on this walk and the platform is what
            # explains why - and it must be a candidate still worth trying when
            # the platform comes back, not one the record says was ruled out.
            judged=False,
            performed=False
        )

    logger.warning("action could not be performed", exc_info=error,
                   extra={"action_type": action_type})

    # What the tier said it left, where a tier said anything. A refusal can
    # follow a change - a rollback refused after the sync was suspended - and
    # the row this outcome writes is the only record of it. Anything that is not
    # a tool's answer said nothing about the estate, so nothing about it is
    # known - unless nothing could have been written, which is what a plan is.
    told = error if isinstance(error, McpToolError) and could_have_written else None

    return Outcome(
        verdict=Verdict.ESCALATED,
        left_behind_known=(
            told.left_behind_known if told is not None else not could_have_written
        ),
        detail=f"could not {intent}: {_in_its_own_words(error)}",
        not_performed_because=_in_its_own_words(error),
        undo_descriptor=told.undo_descriptor if told is not None else None,
        # Nothing was performed and so nothing was watched. This is the broadest
        # of the three and the one most likely to be reached by something nobody
        # foresaw, which is the best reason for it to say what it knows rather
        # than let the verdict be read for it.
        judged=False,
        performed=False
    )


def _without_the_marker(exhausted: ActionExhausted) -> str:
    """The refusal's own words, without the token that classified it.

    The marker is how the transport tells an exhausted action from any other
    refusal, and it has done that job by the time this reads the message. What
    goes into the detail is read by a person - in the timeline, in the postmortem,
    in a Slack line - and `argus:action-exhausted` in the middle of a sentence
    tells them nothing the verdict beside it has not already said.

    Removed rather than left for the reader to skip, and removed here rather than
    at the source: the transport is right to carry it, since a caller that wanted
    to match on the token still can.
    """
    return str(exhausted).replace(EXHAUSTED_ACTION_MARKER, "").strip()


def _without_the_platform_marker(unreachable: PlatformUnreachable) -> str:
    """The failure's own words, without the token that classified it and without
    the descriptor it carried.

    `_without_the_marker`'s reasoning, for the other marker, and one more thing
    to take out. This failure may carry what the action left behind, and that
    travels as JSON in the same string - so a detail built from it raw would put
    an object in the middle of a sentence a person reads in the timeline, the
    postmortem and a Slack line. The descriptor is on the outcome, where
    something can act on it; here it is noise.

    The payload is removed by `mcp_transport` rather than here,
    because the shape of it is that module's and a caller cannot strip what it
    was never told the shape of.

    Kept as its own function rather than one taking a token, because the two are
    typed on what they strip: a single helper would take an `McpToolError` and
    could then be handed either exception with either marker, which is precisely
    the mix-up the two branches above exist to prevent.
    """
    return without_the_payload(
        str(unreachable).replace(UNREACHABLE_PLATFORM_MARKER, "")
    ).strip()


def _in_its_own_words(failure: Exception) -> str:
    """A failure that was no answer of a kind, in its own words: without the
    token that says the tier knows what it left, and without what it left.

    `_without_the_platform_marker`'s reasoning, for the ordinary refusal. Taking
    any exception rather than a tool's alone, because the branch it serves
    catches everything - and a failure carrying neither leaves here as it
    came."""
    return without_the_payload(
        str(failure).replace(LEFT_BEHIND_KNOWN_MARKER, "")
    ).strip()


class _Settled(NamedTuple):
    """What watching the service concluded, and why it concluded it.

    The reason travels with the verdict because one verdict is reached two ways
    that mean different things. `ESCALATED` covers a service that could not be
    read and a change the platform never applied, and an account that described
    both as "could not be read" would tell a person to go looking at a monitoring
    system when what had happened was a held rollout. So the sentence is written
    where the finding is made rather than guessed at by whoever reports it.
    """

    verdict: Verdict
    because: str


# What a wait a person ended - resolved or withdrawn - settles as, wherever in a
# pass it is asked.
_ENDED_DURING_THE_WAIT = _Settled(
    Verdict.STOPPED,
    "a person ended the incident before the verification wait reached a verdict"
)

# What a wait on the rule that paged settles as where the rule was read and every
# evaluation read still spanned minutes from before the change. `ESCALATED`, not
# `REFUTED`: none of them judged anything the change did, so refuting would put
# back a change that may have worked, on a measurement nobody took.
_NO_EVALUATION_SINCE_THE_CHANGE = _Settled(
    Verdict.ESCALATED,
    "no evaluation of the rule that fired covered only the time since the change "
    "before the time allowed ran out - so nothing was measured either way"
)

# What a wait settles as where the service was read before the deadline and
# could not be read from it on, for as long as a read may go unanswered.
# `ESCALATED`, not `REFUTED`: a look that landed before the deadline could have
# confirmed a recovery, but none was late enough to rule one out.
_NOT_READ_SINCE_THE_DEADLINE = _Settled(
    Verdict.ESCALATED,
    "the service could not be read once the time allowed had run out, and every "
    "look before then was too early to rule a recovery out - so nothing was "
    "measured either way"
)

# The same, on the rule's path: an evaluation since the change was read before
# the deadline, and the rule could not be read from it on.
_RULE_NOT_READ_SINCE_THE_DEADLINE = _Settled(
    Verdict.ESCALATED,
    "the rule that fired could not be read once the time it allows had run out, "
    "and every evaluation before then was too early to rule its stopping out - "
    "so nothing was measured either way"
)


def _what_watching_the_service_settled(fetch_metrics: Callable[[], list[MetricBucket]],
                                       has_arrived: HasArrived,
                                       now: Clock,
                                       sleep: Sleeper,
                                       still_wanted: StillWanted,
                                       settings: MitigationSettings,
                                       thresholds: AnomalyThresholds,
                                       action_type: ActionType,
                                       acted_from: datetime,
                                       incident_id: str | None = None,
                                       publisher: Publisher = nobody,
                                       onset: datetime | None = None,
                                       read_the_rule: (
                                           Callable[[], AlertRuleStanding] | None
                                       ) = None,
                                       incident_began: str | None = None) -> _Settled:
    """What the service did once the change was in force, within the time the
    recovery it is waiting for needs.

    Two questions rather than one, and which of them decides is read off the
    window rather than off the incident's mode. Where the minutes an incident is
    about were never published, the action was taken to restore the *sight* of the
    service, and what answers it is readings existing again - not readings sitting
    at a baseline, because a window nobody could read has no baseline to return to.
    Everywhere else the levels decide - except where `read_the_rule` is given,
    and then the rule that paged decides before either question is asked, and
    the window only dates the recovery.

    The distinction is drawn over the span between the onset and the action, which
    is historical and settled by the time this runs. Asked of the minutes *after*
    the action instead it would answer the same for every incident on the first
    pass - no minute has finished yet - and asked of the window as a whole it would
    be overturned by the readings the action itself brought back, which arrive
    within the minute.

    Where that span ends is `acted_from`, when the action's claim was written:
    the latest moment known to come before the write was sent, on the walk's own
    clock as the arrival and the deadlines are - never the moment its answer
    came back. The call can straddle a minute, and the service restores its rows
    from its own minute of the change: dated by the answer, that minute counted
    as before the action, the rows the action brought back read as the sight
    having been there all along, and a blind spot was refuted on its first look
    for a window that never departed. Everything after the action - the first
    minute a verdict is read from, the deadlines - is still dated by the change
    arriving.

    An onset of `None` is every incident whose onset was measured rather than
    stated, and a measured onset means the window held a departure to measure it
    from. So the question does not arise there, and it is vacuous wherever an
    incident was dated and watched - silent data corruption among them, whose
    window carries every minute and merely holds them flat.

    `None` also means *nobody handed one over*, and the two are indistinguishable
    here by construction. That is safe only while every caller that has an onset
    passes it: `apps.worker.assembling` binds this function directly for that
    reason. Route the walk through a seam one argument wide instead and a blind
    spot would be judged on levels it does not have, with nothing anywhere saying
    so - which is the one way this parameter can fail quietly.

    How long it is given is read off the service's own window rather than
    configured - `_when_a_recovery_would_have_shown` - or, where the rule that
    paged judges, off the rule - `_when_the_rule_would_have_resolved`. A picked
    figure is wrong in both directions at once.

    Whether that time has run out is asked of when each look was asked for, not
    of when it answered. A look carries the service as it stood when it was
    asked, so one asked in time and answered late is a look the wait was owed.
    Judged by its arrival, a shop slow to answer settled the wait on a window
    from before the minute the verdict is read from had begun, and a rollback
    that worked was put back.

    `REFUTED` on expiry rather than an error, because that is a real answer
    about the world: the action was taken, the service was looked at, and it did
    not visibly help in the time it was given. Calling it an error would route an
    incident to a human over what is ordinary evidence against a hypothesis.

    `ESCALATED` where the window ran out with the service never once read. That
    is the same expiry and the opposite finding: the first is a measurement that
    went against the hypothesis, this is no measurement at all, and only one of
    them is evidence.

    And a look is owed at the deadline, not only before it. The deadline is where
    the minutes a recovery would show in have all been reported, so a look before
    it can confirm one but is too early to rule one out - and a refutation read
    off the last of them, because the look at the deadline timed out, put back
    a change whose recovery the next look would have read. So a look that fails
    from the deadline on is taken again, for as long as a read may go unanswered
    (`mitigation_verification_timeout_seconds`); the look that lands decides, and
    where none does it is `ESCALATED`, since nothing measured what the change
    did. The rule's path owes the same look: its deadline is the evaluation from
    which a rule still firing rules its stopping out, and an evaluation before
    it can confirm the change but not refute it.

    Nor does a read of whether the change has arrived end the walk where it
    fails: it costs its pass, as a read of the service does, and the wait for the
    change still ends at the configured bound.

    `STOPPED` where a person ended the incident while this was waiting. The
    loop already wakes every ten seconds to re-read the metrics, so asking here
    costs nothing and ends the wait within one interval of the ending rather than
    at the end of a window nobody is waiting for.

    Each look is published. This is the one stretch of an incident where Argus
    is doing something and has nothing to show for it yet, and a page that went
    quiet here would read as a page that had stopped.
    """
    started_at = now()
    # What bounds the stretch where nothing has been measured: the change still
    # arriving, or a service that will not answer a read. How long to *watch* is
    # read off the window below, and until a window has come back there is
    # nothing to read it off - the only facts are that an action was taken and
    # that nothing has answered, and a configured figure is all either of them
    # supports. The same figure bounds the looks owed at the deadline: a look
    # that fails there is a service that will not answer a read, again.
    a_read_may_go_unanswered_for = timedelta(
        seconds=settings.mitigation_verification_timeout_seconds
    )
    nothing_measured_by = started_at + a_read_may_go_unanswered_for

    arrived_at = _when_the_change_reached_the_service(
        has_arrived, now, sleep, started_at, nothing_measured_by
    )

    if isinstance(arrived_at, _Settled):
        return arrived_at

    # The first minute that wholly followed the change being in force, and the
    # instant it began. Dated from the arrival rather than from the call, because
    # the minutes before a change reaches the last replica are minutes the code it
    # replaced was serving - and the minute the action itself fell inside is
    # aggregated over seconds either side of it, which can only blur the two
    # states together.
    first_minute_begins = (arrived_at + timedelta(minutes=1)).replace(
        second=0, microsecond=0
    )
    first_whole_minute = to_iso_minute(first_minute_begins)

    def say(
        event: AwaitingRecovery | RecoveryChecked | RetrievalUnanswered
    ) -> None:
        """Narrates the wait, where there is an incident to narrate it for."""
        if incident_id is not None:
            publish(event, publisher)

    # Whether the service was ever actually looked at. What the expiry below
    # means depends entirely on it: a window that ran out having read the shop
    # and found it still bad is a refutation, and a window that ran out having
    # read nothing is not a verdict at all.
    anything_was_read = False
    # When to stop watching: the configured bound while nothing has been
    # measured, and the window's own answer from the first reading that comes
    # back.
    watch_until = nothing_measured_by
    # Whether this incident's own minutes were ever published, which decides which
    # of the two questions above is asked. `None` until a read answers, because it
    # is measured from a window rather than declared by a caller.
    the_sight_was_absent: bool | None = None
    # The wait as measured off the first window that answered, held until a
    # verdict is read off the minutes it names - `None` once said, or where none
    # is due.
    the_wait: AwaitingRecovery | None = None
    # Whether the rule that paged was ever read, and whether any evaluation read
    # covered only the time since the change. The second is what decides what
    # running out of time means on that path, as `anything_was_read` does on
    # this one: an evaluation over minutes from before the change judged nothing
    # the change did, so a wait that read only those measured nothing.
    the_rule_was_read = False
    an_evaluation_since_the_change_was_read = False

    while True:
        # Asked before each look rather than only after it. A walk somebody
        # stopped has been answered, and a look taken after that - announced on
        # the first pass, and posted to Slack - tells them Argus is still at it.
        if not still_wanted():
            return _ENDED_DURING_THE_WAIT

        # What every deadline below is held to, read once for the whole look and
        # before any of it is asked.
        asked_at = now()

        # A read that cannot be taken costs this pass and nothing more. The loop
        # is already a poll against a deadline, so a reading that did not arrive
        # is the one kind of failure it is built to absorb - and the alternative
        # was the whole incident: nothing above this catches it, so the walk
        # stopped mid-action, no verdict was recorded, and the incident kept
        # whatever status it was walking under.
        buckets: list[MetricBucket] | None
        unanswered: Exception | None = None
        try:
            buckets = fetch_metrics()
        except Exception as error:
            logger.warning("metrics could not be read", exc_info=True)
            buckets = None
            unanswered = error

        # And asked again once the read is back, before anything is said. A read
        # on a fast clock is long enough for the stop to land inside it, and
        # whatever this pass says next - that the read went unanswered, the
        # wait, what the look found - would be said after the person was
        # answered.
        if not still_wanted():
            return _ENDED_DURING_THE_WAIT

        if unanswered is not None and incident_id is not None:
            say(RetrievalUnanswered(
                incident_id=incident_id,
                what_was_asked="the service's metrics",
                because=str(unanswered),
                minute=first_whole_minute
            ))

        if buckets is None and read_the_rule is not None:
            # On the rule's path the window only dates the recovery, so a window
            # that could not be read costs that date and nothing more: the rule
            # is still asked, and its deadline still decides.
            buckets = []
        elif buckets is None:
            # The deadline still decides, and it is held to the moment this look
            # was asked, as an answered one is. A failure asked for in time is
            # owed the look after it, as a late answer would have been.
            #
            # What it decides, though, is not `REFUTED` where nothing was ever
            # read. That word means the explanation was tested and did not hold,
            # and acting on it undoes the change and strikes the candidate off -
            # so a mitigation that worked would be reversed, the service broken
            # again, and the cause that was right removed from the list, on a
            # measurement nobody took. Both times this was seen against the real
            # stack the service had in fact recovered. `ESCALATED` is the member
            # that already means no verdict was reached at all, and the one this
            # is: Argus cannot say, so a person is asked.
            if asked_at >= watch_until and not anything_was_read:
                logger.warning("nothing was measured before the deadline")

                return _Settled(
                    Verdict.ESCALATED,
                    "the service could not be read once before the time "
                    "allowed ran out - so nothing was measured either way"
                )

            # Nor where the service was read, but only before the deadline. Each
            # of those looks could have confirmed a recovery, and none that did
            # not was late enough to rule one out - so refuting on the last of
            # them judged the change on minutes it had not had. The look owed is one
            # from the deadline on, and it is asked again until one lands or a
            # read has gone unanswered as long as one may.
            if asked_at >= watch_until + a_read_may_go_unanswered_for:
                logger.warning("nothing was measured after the deadline")

                return _NOT_READ_SINCE_THE_DEADLINE

            sleep(_SECONDS_BETWEEN_METRIC_READS)
            continue

        if not anything_was_read and read_the_rule is None:
            # The first window to come back is what says how long this wait
            # lasts, and it says it once. Re-derived on every pass it would be a
            # moving deadline: a service still flapping extends the rhythm it is
            # being judged by, so the wait would grow for exactly as long as the
            # service kept misbehaving and the verdict would never be reached.
            watch_until = _when_a_recovery_would_have_shown(
                first_minute_begins, buckets, thresholds,
                reporting_lag_minutes=settings.metrics_reporting_lag_minutes
            )

            # Measured here rather than before the first read, because the
            # figure is measured off that window: said earlier it would be a
            # guess, and the page and the Slack line both say it aloud. A wait
            # whose reads never answer therefore announces nothing - what the
            # page carries then is a line per unanswered read, which is the same
            # thing this was there to prevent.
            #
            # Held rather than said, and said before the first verdict read off
            # the minutes it names. The receipt and a window that never departed
            # settle this same pass on no minute at all, and announced before
            # them the page said "Waiting ... up to 104s" and gave the verdict
            # 44 ms later.
            if incident_id is not None:
                the_wait = AwaitingRecovery(
                    incident_id=incident_id,
                    from_minute=first_whole_minute,
                    seconds_allowed=(watch_until - arrived_at).total_seconds()
                )

        anything_was_read = True
        # An incident paged by a rule watching a series is judged by that rule.
        # It defines what is acceptable for the service, and it sees what one
        # window of minutes cannot: a flap with no rhythm hands the levels a
        # clear minute, and a rule looking back far enough goes on firing.
        #
        # Asked before anything below, because everything below is the levels
        # deciding - a window that never departed, a receipt, readings returning
        # - and an action the rule judges gets no verdict from the levels. The
        # window is read here only to date the recovery.
        if read_the_rule is not None:
            try:
                standing = read_the_rule()
            except Exception as rule_unanswered:
                logger.warning("alert rule could not be read", exc_info=True)

                # Asked after the rule's read for the reason it is asked after
                # the window's.
                if not still_wanted():
                    return _ENDED_DURING_THE_WAIT

                if incident_id is not None:
                    say(RetrievalUnanswered(
                        incident_id=incident_id,
                        what_was_asked="the alert rule that fired",
                        because=str(rule_unanswered),
                        minute=first_whole_minute
                    ))

                # Never refuted on a failed read. An evaluation read before the
                # deadline could have confirmed the change, but one still firing
                # was too early to rule its stopping out - and refuting on it
                # puts the change back on a measurement nobody took.
                # The look owed is one from the deadline on, asked again as the
                # levels' is.
                if asked_at >= watch_until and not the_rule_was_read:
                    logger.warning("nothing was measured before the deadline")

                    return _Settled(
                        Verdict.ESCALATED,
                        "the rule that fired could not be read once before "
                        "the time allowed ran out - so nothing was measured "
                        "either way"
                    )

                if asked_at >= watch_until + a_read_may_go_unanswered_for:
                    logger.warning("nothing was measured after the deadline")

                    return (
                        _RULE_NOT_READ_SINCE_THE_DEADLINE
                        if an_evaluation_since_the_change_was_read else
                        _NO_EVALUATION_SINCE_THE_CHANGE
                    )

                sleep(_SECONDS_BETWEEN_METRIC_READS)
                continue

            if not still_wanted():
                return _ENDED_DURING_THE_WAIT

            if not the_rule_was_read:
                # Read off the rule once, as the metrics' deadline is read off
                # the first window: how far back it looks, plus one evaluation,
                # plus how long it keeps firing, plus the source's lag.
                watch_until = _when_the_rule_would_have_resolved(
                    arrived_at, standing,
                    reporting_lag_minutes=settings.metrics_reporting_lag_minutes
                )

                if incident_id is not None:
                    say(AwaitingRecovery(
                        incident_id=incident_id,
                        from_minute=first_whole_minute,
                        seconds_allowed=(watch_until - arrived_at).total_seconds()
                    ))

            the_rule_was_read = True
            # Only an evaluation whose whole range followed the change says
            # anything about it; one that began before may have caught a lull the
            # action had no part in. So a look at one that began before has judged
            # nothing yet, firing or quiet. Said as still at the incident's level,
            # a look a second after a revert was read as the verdict.
            followed_the_change = (
                standing.evaluated_at - timedelta(seconds=standing.range_seconds)
                >= arrived_at
            )
            resolved = standing.is_normal and followed_the_change
            an_evaluation_since_the_change_was_read = (
                an_evaluation_since_the_change_was_read or followed_the_change
            )
            came_back_at = (
                find_recovery(buckets, thresholds, since=incident_began)
                if resolved else None
            )

            if incident_id is not None:
                say(RecoveryChecked(
                    incident_id=incident_id,
                    minute=first_whole_minute,
                    recovered=resolved,
                    recovered_minute=came_back_at,
                    saw_no_minute=not followed_the_change
                ))

            if not still_wanted():
                return _ENDED_DURING_THE_WAIT

            if resolved:
                return _Settled(
                    Verdict.CONFIRMED, "the rule that fired stopped firing"
                )

            if asked_at >= watch_until:
                if not an_evaluation_since_the_change_was_read:
                    logger.warning("nothing was measured before the deadline")
                    return _NO_EVALUATION_SINCE_THE_CHANGE

                return _Settled(
                    Verdict.REFUTED,
                    "the rule that fired was still firing when the time it "
                    "allows ran out"
                )

            sleep(_SECONDS_BETWEEN_METRIC_READS)
            continue

        # Measured on the first pass that answered and not revisited: the span it
        # asks about ended when the action was taken, so a later pass would be
        # answering about a window the action itself has already changed. Ended
        # at the minute the action is dated from rather than the one it arrived
        # in: a write's answer can come back in the minute after the service
        # acted, and the service restores its rows from its own minute.
        if the_sight_was_absent is None:
            the_sight_was_absent = _nothing_was_seen_between(
                buckets, onset, to_iso_minute(acted_from)
            )
            # What the wait waits for, said once this is known and before the
            # wait is: on a blind spot, for the minutes to be published again -
            # said as a level to come down from, it promised a reading nobody
            # took.
            if the_wait is not None and the_sight_was_absent:
                the_wait = the_wait.model_copy(update={"until_read_again": True})

        if the_sight_was_absent and has_a_reading_since(buckets, first_whole_minute):
            if the_wait is not None:
                say(the_wait)

            # The look that saw the rows back, said as every other look is: left
            # unsaid, the page went from "no new minute read yet" straight to the
            # verdict, and nothing recorded which minute came back. Dated by the
            # first row after the onset rather than by the minute the verdict is
            # read from - the rows returning is a fact about the service, and
            # where the action restored them that is the minute it fell inside.
            if incident_id is not None and onset is not None:
                say(RecoveryChecked(
                    incident_id=incident_id,
                    minute=first_whole_minute,
                    recovered=True,
                    recovered_minute=min(bucket.bucket_id for bucket in buckets
                                         if bucket.bucket_id >= to_iso_minute(onset)),
                    read_again=True
                ))

            return _Settled(
                Verdict.CONFIRMED, "the service could be read again"
            )

        # What both rules below are measured against, and asked once because it
        # is one fact about one window. A departure is what makes a recovery
        # measurable at all: `has_recovered_since` reports every minute of a
        # window without one as recovered - true of the minutes, and silent about
        # whether anything was ever wrong - so acting on that alone confirms
        # whatever was just done on the strength of a window that was never
        # evidence of anything. Asked here, on the first window that answered,
        # because that is where the window finally exists to be asked about.
        departed = has_a_departure_in_it(buckets, thresholds)

        # An action that answers with what it changed is settled by its own
        # answer wherever the window holds no departure to judge it by - and it
        # holds none whether the series were flat or nobody published them at
        # all. The two are one state as far as a receipt is concerned: there is
        # no level to come back down, so a count of what is gone from the store
        # is the only evidence there will ever be.
        #
        # Asked without regard to `the_sight_was_absent`, which is what this
        # answers for. That measurement exists to keep a blind spot from being
        # refuted before its rows return, and it is the right question for a kind
        # whose verdict a level has to carry. For a kind carrying its own, it
        # withheld the one confirmation available: an incident moving no series
        # publishes no minutes between its onset and the action, so the sight
        # reads as absent for a fully observed service and the receipt was never
        # reached. Not asked where a series *did* depart, though - a discard that
        # left the service failing is an explanation the evidence has not borne
        # out, like any other. That one goes past the refutation below as well,
        # whose question is also whether anything departed, and is judged on
        # levels by the recovery check and the deadline: confirmed if the level
        # came down, refuted when the time runs out, exactly as every other kind
        # is.
        if not departed and the_kind(action_type).reports_what_it_changed:
            return _Settled(
                Verdict.CONFIRMED,
                "the store reported what it removed, which is the whole of "
                "what was wrong"
            )

        # Refused to an incident whose sight was absent, which is the split this
        # function is built around. A departure is a fact about levels, and a
        # window nobody could read has no baseline to depart from - so a blind
        # spot holds no departure for the same reason it holds no readings, and
        # refuting it here would refute the one incident whose window is
        # legitimately empty, one pass before the rows return and confirm it. The
        # first rule in this block - readings existing again - is what answers
        # that incident.
        #
        # So what reaches this point is an incident whose minutes were published,
        # never moved, and whose action does not answer for itself. For that one
        # there is no evidence left to wait for: no level departed, so none can
        # come back, and nothing the action did says otherwise.
        if not the_sight_was_absent and not departed:
            return _Settled(
                Verdict.REFUTED,
                "nothing in this window ever departed, so there was no "
                "improvement for it to show"
            )

        recovered = has_recovered_since(buckets, first_whole_minute, thresholds)
        # Which minute the service came back at, asked only where it has come
        # back - and asked of the whole window rather than of the minutes since
        # the action. The two questions are different and only one of them is
        # about Argus: whether this action worked is judged from the action, so
        # a relapse after it refutes the action, where when the service recovered
        # is a fact about the service and is true whenever it happened. Bounding
        # the second question at the action would answer the action's own minute
        # for every service that had already come back before Argus got there,
        # which is the attribution this is recorded to make visible.
        #
        # `None` where nothing can be dated: the verdict is reached on a window
        # whose departure need not have persisted, and a window with no incident
        # in it has no recovery to report. The postmortem computes its own
        # answer where this is absent, so an undatable confirmation costs the
        # document nothing.
        came_back_at = (
            find_recovery(buckets, thresholds, since=incident_began)
            if recovered else None
        )

        if the_wait is not None:
            say(the_wait)
            the_wait = None

        if incident_id is not None:
            say(RecoveryChecked(
                incident_id=incident_id,
                minute=first_whole_minute,
                recovered=recovered,
                recovered_minute=came_back_at,
                # Not recovered, and not still failing either: nothing since the
                # change has been read to say which.
                saw_no_minute=not any(bucket.bucket_id >= first_whole_minute
                                      for bucket in buckets)
            ))

        # Asked before the recovery is acted on, and it outranks it: an incident
        # somebody withdrew is over whichever way this minute reads, and
        # claiming a confirmation on the pass the walk was stopped would credit
        # Argus with an ending it did not reach.
        if not still_wanted():
            return _ENDED_DURING_THE_WAIT

        # What the looks judge, in their words: whether the service left the
        # incident's level - never whether it was back at a baseline, which no
        # look measures.
        if recovered:
            return _Settled(
                Verdict.CONFIRMED, "the service was no longer at the incident's level"
            )

        if asked_at >= watch_until:
            return _Settled(
                Verdict.REFUTED,
                "the service was still at the incident's level when the verification "
                "wait ran out"
            )

        sleep(_SECONDS_BETWEEN_METRIC_READS)


def _when_the_change_reached_the_service(has_arrived: HasArrived,
                                         now: Clock,
                                         sleep: Sleeper,
                                         started_at: datetime,
                                         no_later_than: datetime
                                         ) -> datetime | _Settled:
    """The moment the change took effect on the service, or why nothing about it
    can be measured.

    Asked before anything is read, because until the change is in force the
    minutes describe the code it was meant to replace - so a verdict taken from
    them is a verdict about the wrong deployment, which is how a mitigation that
    worked comes to be refuted and put back.

    The platform saying it has stopped is what ends this without a figure. A
    rollout stopped part way satisfies neither count and never will, so a loop
    that only asked "arrived yet" would poll until its lease expired and leave the
    change applied for another worker to find. A rollout stopped after it finished
    is an arrival like any other. Reported as a state rather than judged as a
    duration - see `Arrival`.

    `ESCALATED` both ways out and never `REFUTED`, because nothing about the
    hypothesis was tested: the change never reached the service. Refuting would
    mark it tested, put it back and strike the explanation off, on no measurement
    at all - and the explanation may have been the right one. The two sentences
    differ because the states do: a platform that has given up is something a
    person can act on, where a wait that ran out may still be converging.

    The moment answered is the one that pass was read at, and the first pass is
    `started_at` rather than a second reading of the clock. A change in force on
    the first ask was in force when the action was performed, so reading the clock
    again would date it later than it happened - and this is what the minute a
    verdict is read from is counted from.

    A read of the platform that fails costs its pass and nothing more, as a read
    of the service does. Raised, it ended the walk mid-action, and the worker put
    the change back and handed the incident to a person - a rollback undone on
    no measurement. At the bound it is `ESCALATED` too, said as a question nobody
    could answer rather than as a change that had not arrived.
    """
    moment = started_at

    while True:
        try:
            arrival: Arrival | None = has_arrived()
        except Exception:
            logger.warning("arrival could not be read", exc_info=True)
            arrival = None

        if arrival is Arrival.ARRIVED:
            return moment

        if arrival is Arrival.WILL_NOT_ARRIVE:
            logger.warning("change will not arrive")

            return _Settled(
                Verdict.ESCALATED,
                "the platform stopped applying the change, so it never applied "
                "and nothing about it was measured"
            )

        # Checked before sleeping for the reason every other wait here checks it
        # first: a window that has run out must not buy another interval by having
        # been busy. Said as what the last read found: a change still arriving,
        # or a platform nobody could ask, which is not a change that had not
        # arrived.
        if moment >= no_later_than and arrival is None:
            logger.warning("nothing was measured before the deadline")

            return _Settled(
                Verdict.ESCALATED,
                "whether the change had reached the service could not be read "
                "before the time allowed ran out - so nothing about it was measured"
            )

        if moment >= no_later_than:
            logger.warning("change did not arrive in time")

            return _Settled(
                Verdict.ESCALATED,
                "the change had not reached the service before the time "
                "allowed ran out - so nothing about it was measured"
            )

        sleep(_SECONDS_BETWEEN_METRIC_READS)
        moment = now()


def _when_a_recovery_would_have_shown(first_minute_begins: datetime,
                                      buckets: Sequence[MetricBucket],
                                      thresholds: AnomalyThresholds,
                                      reporting_lag_minutes: int) -> datetime:
    """The moment past which there is nothing left to wait for.

    The clear minutes a recovery has to show, counted from the first minute that
    could be one of them, ending when the last of them has finished - and then
    reported. After that instant no further waiting can change the answer: the
    minutes that would have carried the recovery are all in the past and judged.

    Reported is the metrics source's own lag. A source that reports a minute
    only once it has ended hands over the last of them a minute after it
    finished, and a wait that stopped as it finished would refute the action
    that worked for want of a reading still on its way - which is what a
    rollback met the first time the walk read such a source.

    How many is the window's own answer rather than a setting -
    `minutes_a_recovery_must_hold`. The figure it replaces was a flat three
    minutes, which is wrong in both directions at once: longer than a step
    incident needs, and far short of the six clear minutes a service failing one
    minute in five has to hold still for. The second direction is the one that
    cost something, because a wait that ends before the evidence could exist
    refutes the mitigation that worked and puts it back.

    From the *beginning* of the first whole minute and not from the arrival, which
    is the one place a minute of arithmetic matters. A change in force at 11:11:00
    exactly has 11:12 as its first whole minute, and a deadline set an arrival
    plus one minute later falls at 11:12:00 - the instant that minute begins, with
    no seconds elapsed in it, which is no reading rather than a quiet one. Every
    action taken on a minute boundary would then be refuted for want of a bucket
    that could not exist yet.

    This module's arithmetic rather than `core`'s, because `core` has
    no clock: it answers in minutes, which is what a window is made of, and
    turning that into an instant needs the moment the wait started from.
    """
    return first_minute_begins + timedelta(
        minutes=minutes_a_recovery_must_hold(buckets, thresholds) + reporting_lag_minutes
    )


def _when_the_rule_would_have_resolved(arrived_at: datetime,
                                       standing: AlertRuleStanding,
                                       reporting_lag_minutes: int) -> datetime:
    """The moment past which a rule still firing is an answer.

    A change that worked has left the rule's range once the range has passed
    since it arrived, and the next evaluation sees that. A rule that keeps firing
    for a while after its condition clears says so that much later. The source's
    lag is added for the reason the metrics' deadline adds it: the minutes the
    rule reads arrive `reporting_lag_minutes` late from a source that reports
    them once they end.

    The sum is then carried to the rule's next evaluation after it, because the
    rule evaluates on its own ticks and not on the change's: a change arriving a
    tenth of a second after a minute turned is first judged a whole interval
    after its range has passed, and a deadline ending a tenth of a second after
    that evaluation left one look to read it, which read the evaluation before -
    and a revert that had worked was put back.

    Every term but the lag is the rule's own; the lag is the one setting, and
    the levels' deadline adds the same one.
    """
    interval = timedelta(seconds=standing.interval_seconds)
    unrounded = arrived_at + timedelta(
        seconds=(
            standing.range_seconds
            + standing.interval_seconds
            + standing.keep_firing_for_seconds
        ),
        minutes=reporting_lag_minutes
    )

    # A rule with no interval has no next evaluation to carry the wait to.
    if not interval:
        return unrounded

    return standing.evaluated_at + ((unrounded - standing.evaluated_at) // interval + 1) * interval


def _nothing_was_seen_between(buckets: Sequence[MetricBucket],
                              onset: datetime | None,
                              acted_in_minute: str) -> bool:
    """Whether the incident ran its course with none of it published.

    The minutes from the onset up to the action, asked of the readings that
    describe them. An incident anybody could watch has those minutes - they are
    what its onset was measured from - and one nobody could watch has none of
    them, which is the whole of what a monitoring blind spot is.

    `acted_in_minute` is the minute the action itself fell inside - dated from
    a moment known to come before the write was sent, never from its answer -
    and the slice stops strictly before it. That minute is aggregated over
    seconds either side of the change, so it describes neither the service
    that was failing nor the one that was fixed - and where an action restores
    the sight, it is the first minute the rows come back in. Counted as
    evidence the sight was there, it answers this question with the very thing
    the action did about it, and the incident is then judged on levels whose
    absence was the incident.

    One minute later - the first that wholly followed the change - is the
    watching window's own start, and it is the wrong end of this span for the
    same reason it is the right start of that one.

    False for an undated incident rather than unknown. An onset arrives here only
    where an alert stated one, and a stated onset is the only kind this question
    can be asked about: a measured one was derived from minutes that therefore
    exist.
    """
    if onset is None:
        return False

    return not has_a_reading_since(
        [bucket for bucket in buckets if bucket.bucket_id < acted_in_minute],
        to_iso_minute(onset)
    )


def _why_nothing_was_put_back(action_type: ActionType) -> str:
    """Why a refuted action of this kind left nothing behind it.

    Two sentences for one absent descriptor, because the absence means two
    things. A restart changed nothing that outlives it, so there was never
    anything to put back and nothing was given up by not trying. A discard
    changed something real - figures are gone from the store - and still owes
    no undo, because what it removed was a copy of records it never touched
    and writing them back would recreate the incident.

    Said the wrong way round, the second reads as the first: a reader deciding
    whether to go and look at the cache would be told Argus had never been in
    it. That is the one sentence this must not produce.
    """
    if changes_something_persistent(action_type):
        return "no undo was owed"

    return "there was nothing to put back"


def _undone(performed: Performed,
            undo: UndoChange,
            undoing_kinds: UndoingKindOf,
            action_type: ActionType,
            because: str) -> Outcome:
    """Puts a refuted action back, and says so as a verdict.

    A refuted action was taken on a hypothesis the evidence has not borne out,
    so leaving its change in place would mean production state was altered for
    a cause that was not the cause, with nobody told.

    An action that left nothing behind is refuted with nothing to undo, and the
    account says so. Not "the undo failed" and not silence: a restart that did
    not help is a hypothesis refuted cleanly, and a reader has to be able to
    tell that from a flag Argus could not put back.

    `action_type` is here because that is two situations rather than one, and
    the descriptor cannot tell them apart - it is absent in both. A restart
    changed nothing that outlives it; a discard changed something real and owes
    nothing back. Taken as a parameter rather than carried on `Performed`,
    which says deliberately that the kind lives on the row the action was
    written to.

    `undoing_kinds` is which kind ends the sentence for a change that really
    was put back, since a flag is put back *on* and a deployment *to* a revision.

    The undo itself is `undo_change`; what this adds is what a *verdict* is
    made of. A change left as found is still a refutation - the wait found
    against it, which is what the verdict is about - while a change nobody
    could account for escalates, because an environment Argus cannot describe
    is precisely what a human needs paging for. So does a change left
    standing: somebody made the subject theirs while the reconciliation Argus
    suspended still stands, and whether to resume it over them is a person's
    to decide.

    `because` is what the verification wait judged, said as it said it: the
    rule still firing, the service still at the incident's level, or a window
    that never showed the incident at all. Three findings that point a reader
    three different ways, so no branch writes one sentence over all of them.
    """
    taken = performed.said
    undo_descriptor = performed.undo_descriptor

    if undo_descriptor is None:
        return Outcome(
            verdict=Verdict.REFUTED,
            left_behind_known=True,
            because=because,
            detail=(
                f"{taken}, but {because}, and "
                f"{_why_nothing_was_put_back(action_type)}"
            ),
        )

    attempt = undo(undo_descriptor)

    # Matched exhaustively rather than tested two at a time with a fallthrough,
    # and the difference is what the unnamed case meant. "Anything else" here
    # was the restore's sentence - *so it was put back* - so a fourth outcome
    # would have been reported as a change that was written back, which is the
    # one claim an account must never make falsely. `assert_never` turns that
    # into a type error against a member nobody has added yet, before anything
    # runs.
    match attempt.outcome:
        case Undone.NOT_ESTABLISHED:
            logger.error("change could not be put back", extra={
                "action_type": action_type, "subject": attempt.subject, "detail": attempt.detail
            })

            return Outcome(
                verdict=Verdict.ESCALATED,
                left_behind_known=True,
                because=because,
                detail=f"{taken}, but {because}, and [{attempt.subject}] {attempt.detail}",
                undo_descriptor=undo_descriptor,
                undone=attempt.outcome,
                undone_detail=attempt.detail,
            )
        case Undone.LEFT_STANDING:
            # Not a refutation, though the wait found against the change.
            # Somebody made the subject theirs while the reconciliation Argus
            # suspended still stands, and resuming it would overwrite them -
            # so a refutation would close the attempt with Argus's suspension
            # in place and nobody asked about it. A person decides it.
            logger.warning("change left standing", extra={
                "action_type": action_type, "subject": attempt.subject, "detail": attempt.detail
            })

            return Outcome(
                verdict=Verdict.ESCALATED,
                left_behind_known=True,
                because=because,
                detail=f"{taken}, but {because}, and [{attempt.subject}] {attempt.detail}",
                undo_descriptor=undo_descriptor,
                undone=attempt.outcome,
                undone_detail=attempt.detail
            )
        case Undone.LEFT_AS_FOUND:
            return Outcome(
                verdict=Verdict.REFUTED,
                left_behind_known=True,
                because=because,
                detail=f"{taken}, but {because}, and [{attempt.subject}] {attempt.detail}",
                undo_descriptor=undo_descriptor,
                undone=attempt.outcome,
                undone_detail=attempt.detail,
            )
        case Undone.RESTORED:
            # The undo's own telling where it gave one: the kind's ending is how
            # a change of its kind is usually put back, and not every put-back
            # is - a count left to an autoscaler was put back to no count.
            told = (
                attempt.said_as
                if attempt.said_as is not None
                else f"it was put back "
                     f"{undoing_kinds(undo_descriptor).put_back_as(undo_descriptor)}"
            )

            return Outcome(
                verdict=Verdict.REFUTED,
                left_behind_known=True,
                because=because,
                detail=f"{taken}, but {because}, so {told}",
                undo_descriptor=undo_descriptor,
                undone=attempt.outcome,
                undone_detail=attempt.detail,
            )
        case Undone.NO_UNDO_WAS_OWED:
            # Reached by nothing today: this is what an *unwind* reports for a
            # row that owes no undo, and a kind that owes none records no
            # descriptor, so the branch above returns before anything gets
            # here. Answered rather than excluded because the alternative is a
            # narrowing nothing in the types supports - `undo_change` returns
            # an `UndoAttempt`, and every member is a value it may legally
            # carry. The answer is the one the absent-descriptor case gives,
            # so a kind that ever does both says one thing twice.
            return Outcome(
                verdict=Verdict.REFUTED,
                left_behind_known=True,
                because=because,
                detail=(
                    f"{taken}, but {because}, and "
                    f"{_why_nothing_was_put_back(action_type)}"
                ),
                undo_descriptor=undo_descriptor,
                undone=attempt.outcome,
                undone_detail=attempt.detail,
            )

    assert_never(attempt.outcome)
