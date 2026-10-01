"""Taking one proposed action, and judging what the service did (spec §7.3).

The mutating half of the agent. `actions.py` decides what to do without
touching anything; this performs it, waits for the service to answer, and puts
the change back where the answer refutes the hypothesis it was taken on.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import NamedTuple, Protocol, assert_never

from argus_core import to_iso_minute, utc_now
from argus_core.anomaly import (
    AnomalyThresholds,
    find_recovery,
    has_a_reading_since,
    has_recovered_since,
)
from argus_core.events import (
    AwaitingRecovery,
    Publisher,
    RecoveryChecked,
    RetrievalUnanswered,
    nobody,
    publish,
)
from argus_core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    ActionExhausted,
    PlatformUnreachable,
    without_the_payload,
)
from argus_core.models import (
    AutoscalerUndo,
    DeploymentRollbackUndo,
    FlagUndo,
    MetricBucket,
    PinAutoscaler,
    ReplicaUndo,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    UndoDescriptor,
)

from agent_mitigation.actions import (
    Action,
    Outcome,
    UndoAttempt,
    Undone,
    Verdict,
    state_name,
)
from agent_mitigation.tools import (
    Clock,
    MetricsFetcher,
    MitigationSettings,
    PerformingWrites,
    Sleeper,
    StillWanted,
)

__all__ = ["UndoChange", "take_action"]

# How often the service is re-read while waiting for it to answer an action.
# Metrics are aggregated per minute, so a tighter interval only re-reads the
# same four numbers; a looser one spends the verification budget waiting.
_SECONDS_BETWEEN_METRIC_READS = 10.0


class Performed(NamedTuple):
    """What performing one action produced, in the two forms everything after
    it needs.

    `said` is the action in words, and it is built where the action's own
    fields are still in hand - every verdict below quotes it, and a detail
    assembled from an action three branches later is one that has to re-derive
    which kind it was.

    `undo_descriptor` is `None` for an action that changed no persistent state.
    Absent rather than empty: a restart leaves nothing behind, and there is no
    honest descriptor for nothing. What tells that apart from a change nobody
    accounted for is the kind, recorded on the row before the action ran.
    """

    said: str
    undo_descriptor: UndoDescriptor | None


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


def _nobody_stopped_this_walk() -> bool:
    """The default answer to "is this still wanted", for a caller with no walk.

    True rather than a caller being made to supply one: an `Action` is not
    incident-scoped and neither is `take_action`, so a caller with nothing to be
    withdrawn from is the ordinary case. The Orchestrator, which does have a
    walk, passes one that reads the incident.
    """
    return True


def take_action(action: Action,
                settings: MitigationSettings,
                thresholds: AnomalyThresholds,
                fetch_metrics: MetricsFetcher,
                now: Clock = utc_now,
                sleep: Sleeper = time.sleep,
                still_wanted: StillWanted = _nobody_stopped_this_walk,
                incident_id: str | None = None,
                publisher: Publisher = nobody,
                *,
                onset: datetime | None = None,
                writes: PerformingWrites,
                undo: UndoChange) -> Outcome:
    """Performs `action` and answers with what the service then did (spec §7.3).

    Three things happen in order, and the order is the point. The action is
    performed, which is the only moment production state changes. The service
    is re-read until a minute that began *after* that moment can be judged -
    the newest bucket covers the minute in progress, aggregated over seconds
    that are mostly pre-action, so a verdict read off it describes the incident
    rather than the mitigation. And a refuted action is put back, where there
    is anything to put back.

    Which action is performed is the only thing that differs between kinds. The
    waiting and the judging are identical, and deliberately so: a restart and a
    flag revert are answered by the same question - did the service return to
    its baseline - asked of the same numbers by the same rule.

    The verdict rests on the same departure rule that located the onset, so
    Mitigation and the Investigator cannot disagree about whether a given
    minute was healthy - two agents that could would be two incidents.

    An action that could not be taken at all is never `REFUTED`: nothing was
    changed, so there is nothing to judge and nothing to undo, and a verdict here
    would describe an experiment that never ran. Which of the other two it is
    depends on *why* it could not be taken, and the difference decides whether the
    walk goes on. A tier that could not be reached, or that refused after it had
    already changed something, is `ESCALATED` - nobody can say what state
    production is in. A tier that answered and said the action has nowhere left to
    go is `NOT_ATTEMPTED`, and the walk moves to its next candidate: a bound Argus
    holds is not a reason to wake somebody.

    `incident_id` is optional because an `Action` is not incident-scoped and
    neither is this call - a caller with no incident to attribute the wait to
    narrates nothing, which is better than an event hung on an incident that
    was invented to hold it.

    `writes` are the writes that *perform* an action, one per kind, and `undo` is
    what puts one back. Two collaborations rather than one list, because they
    happen at different moments and because the alternative grew by a parameter
    per action kind: the restorers and the check that guards them live on
    `undo_change`, which is where the production binding already assembles them.

    `undo` is required. It used to be optional, composed here from a flag setter
    and a restorer when a caller supplied none - and no caller ever did: the
    Orchestrator has always passed the binding its withdrawal path shares. What
    the default bought was three parameters on this signature that production
    never read, and a second assembly of an undo for a test to exercise instead
    of the one that runs.
    """
    try:
        performed = _perform(action, writes)
    except ActionExhausted as exhausted:
        # Caught before the handler below, and the order is the whole of it: an
        # exhausted action is an `McpToolError` like any other, so a broader
        # `except` reached first would swallow it into an escalation and this
        # branch would never run.
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
            detail=(
                f"did not {_what_it_would_have_done(action)} - "
                f"{_without_the_marker(exhausted)}"
            ),
            # The same thing the paragraph above says in words, said where the
            # candidate's row can read it: nothing was tested, so nothing about
            # this explanation may be recorded as having been.
            measured=False,
        )
    except PlatformUnreachable as unreachable:
        # Caught before the broad handler for the reason above it is: this is an
        # `McpToolError` too, so a broader `except` reached first swallows it into
        # an escalation and this branch never runs.
        #
        # Not `ESCALATED`, because Argus has not run out of moves - it has run
        # out of *this platform's* moves. Four of the five generic mitigations
        # act through the deployment platform, so a platform that is not
        # answering has taken four away at once and left the fifth; escalating
        # here ends a walk whose next candidate is a flag revert on a provider
        # that is still answering.
        #
        # Not `NOT_ATTEMPTED`, which is the distinction worth holding: that says
        # the tier answered and had nowhere left to go - a deployment already at
        # its cap, a floor already at its ceiling - where this says nothing was
        # there to answer. A record carrying it would report a bound that was
        # never reached.
        # Carries what the action left behind, where it left anything. Two of
        # the four actions through the deployment platform suspend its
        # reconciliation before doing what they were asked, so a platform lost
        # after that point leaves an application un-reconciled - and the row
        # this outcome writes is the only record of it. `None` on the ordinary
        # failure, which is the platform going before the first write.
        return Outcome(
            verdict=Verdict.PLATFORM_UNREACHABLE,
            detail=(
                f"did not {_what_it_would_have_done(action)} - "
                f"{_without_the_platform_marker(unreachable)}"
            ),
            undo_descriptor=unreachable.undo_descriptor,
            # The action was not taken, so the service was never watched for it.
            # The candidate is passed over on this walk and the platform is what
            # explains why - and it must be a candidate still worth trying when
            # the platform comes back, not one the record says was ruled out.
            measured=False,
        )
    except Exception as error:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"could not {_what_it_would_have_done(action)}: {error}",
            # Nothing was performed and so nothing was watched. This is the
            # broadest of the three and the one most likely to be reached by
            # something nobody foresaw, which is the best reason for it to say
            # what it knows rather than let the verdict be read for it.
            measured=False,
        )

    settled = _what_watching_the_service_settled(
        fetch_metrics, now, sleep, still_wanted, settings, thresholds,
        incident_id, publisher, onset
    )

    if settled is Verdict.CONFIRMED:
        return Outcome(
            verdict=Verdict.CONFIRMED,
            detail=f"{performed.said} and the service returned to baseline",
            undo_descriptor=performed.undo_descriptor,
        )

    # Left where it is too, and for a reason of its own: nothing was measured,
    # so there is nothing to act on. Putting the change back is what a
    # refutation does, and doing it on no reading at all would reverse a
    # mitigation that may well have worked - which is the shape this was
    # actually seen in, a shop that had recovered while the tier that would have
    # shown it was timing out. The undo goes with it, because what to do about a
    # service nobody could read is a person's to decide.
    if settled is Verdict.ESCALATED:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=(
                f"{performed.said}, and the service could not be read once "
                f"before the time allowed ran out - so nothing was measured "
                f"either way"
            ),
            undo_descriptor=performed.undo_descriptor,
            # Said rather than left to the verdict, which is the same word here
            # as it is for a refutation whose undo failed. What reads this is
            # the candidate's row: a hypothesis marked tested by a wait that
            # took no reading is one a later incident is taught to try last.
            measured=False,
        )

    # Left where it is, carrying what would put it back. Undoing it here would
    # be a second opinion about a decision the withdrawal makes once, for every
    # action the incident took and only where nobody else has been in there
    # since Argus wrote.
    if settled is Verdict.WITHDRAWN:
        return Outcome(
            verdict=Verdict.WITHDRAWN,
            detail=(
                f"{performed.said}, and the incident was withdrawn before the "
                f"service could answer for it"
            ),
            undo_descriptor=performed.undo_descriptor,
            # Nothing was measured here either, and saying so rather than
            # leaving the walk to recognise the word is what lets one fact
            # decide the candidate's row instead of a list of verdicts that has
            # to be kept in step with this one.
            measured=False,
        )

    return _undone(performed, undo)


def _perform(action: Action, writes: PerformingWrites) -> Performed:
    """Does the one thing this action is, and says what it did.

    The only place the kinds part company. Each branch names its own write and
    phrases its own account of it, because the two are one decision: the words
    a verdict quotes have to describe the call that was actually made.

    `assert_never` on the remaining branch, so that a further kind of action is
    a type error here rather than an action performed by falling through to
    whichever branch happened to be last.
    """
    match action:
        case RevertFeatureFlag():
            return Performed(
                said=f"set flag [{action.flag}] {state_name(action.enabled)}",
                undo_descriptor=writes.set_state(action.flag, action.enabled)
            )
        case RestartService():
            restarted = writes.restart(action.service)

            return Performed(
                said=f"restarted [{restarted.service}]",
                # Nothing to put back. A restart changes no persistent state,
                # so there is no prior value to record and no descriptor that
                # would be true.
                undo_descriptor=None
            )
        case RollBackDeployment():
            rolled_back = writes.roll_back(action.application)

            return Performed(
                said=(
                    # The entry it came *from*, which is what the descriptor
                    # records and what a reader needs to know was undone.
                    # Where it went is "the one before", by construction.
                    f"rolled [{action.application}] back off the revision at "
                    f"history entry [{rolled_back.was_on_history_id}]"
                ),
                undo_descriptor=rolled_back
            )
        case ScaleOut():
            scaled = writes.scale_out(action.application)

            return Performed(
                said=(
                    # The count it came *from*, which is what the descriptor
                    # records and what a reader needs to know was undone. Where
                    # it went is the tier's to have decided, and it reports that
                    # figure nowhere a verdict can quote it.
                    f"scaled [{action.application}] out from "
                    f"[{scaled.was_replicas}] replicas"
                ),
                undo_descriptor=scaled
            )
        case PinAutoscaler():
            pinned = writes.pin(action.application)

            return Performed(
                said=(
                    # The floor it came *from*, named as the floor it came from
                    # rather than as the floor it is now - which is the whole care
                    # of this line. The descriptor records the prior floor, and a
                    # sentence that used it to assert a present state would be
                    # false the moment the pin succeeded: "scaling below three"
                    # was already true before Argus acted.
                    #
                    # Where it went, by its number and not by the name of a
                    # bound. The tier asks for whichever is smaller of the
                    # autoscaler's declared ceiling and the most replicas Argus
                    # may hold a deployment at - so "to its ceiling" is false
                    # exactly where Argus's own cap was the binding one, and names
                    # a figure belonging to somebody else's declaration rather
                    # than to anything Argus wrote. The tier records what it
                    # asked for, which is why this can say it.
                    f"raised [{action.application}]'s autoscaler floor from "
                    f"[{pinned.was_min_replicas}] replicas to "
                    f"[{pinned.min_replicas_asked_for}]"
                ),
                undo_descriptor=pinned
            )
        case _:
            assert_never(action)


def _how_it_was_put_back(undo_descriptor: UndoDescriptor) -> str:
    """How the sentence ends when a refuted change really was put back.

    Per kind, because the kinds end the sentence differently: a flag was put
    back *on* or *off*, and a deployment was put back *to* a revision. One
    phrasing covering both would have to be vague enough to say neither.
    """
    match undo_descriptor:
        case FlagUndo():
            return state_name(undo_descriptor.was_enabled)
        case DeploymentRollbackUndo():
            return (
                f"to the revision at history entry "
                f"[{undo_descriptor.was_on_history_id}]"
            )
        case AutoscalerUndo():
            return (
                f"to an autoscaler floor of "
                f"[{undo_descriptor.was_min_replicas}] replicas"
            )
        case ReplicaUndo():
            return f"to [{undo_descriptor.was_replicas}] replicas"
        case _:
            assert_never(undo_descriptor)


def _what_it_would_have_done(action: Action) -> str:
    """The action in words, for a failure that happened before it did anything.

    Separate from `Performed.said`, which reports what *was* done. The two
    differ in tense and in what they may claim: this one is quoted by an
    escalation, where nothing happened and a sentence saying it did would be a
    record of a change nobody made.
    """
    match action:
        case RevertFeatureFlag():
            return f"set flag [{action.flag}] {state_name(action.enabled)}"
        case RestartService():
            return f"restart [{action.service}]"
        case RollBackDeployment():
            return f"roll [{action.application}] back to its previous revision"
        case ScaleOut():
            return f"scale [{action.application}] out"
        case PinAutoscaler():
            return f"stop [{action.application}]'s autoscaler scaling it down"
        case _:
            assert_never(action)


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

    The payload is removed by `argus_core.mcp_transport` rather than here,
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


def _what_watching_the_service_settled(fetch_metrics: MetricsFetcher,
                                       now: Clock,
                                       sleep: Sleeper,
                                       still_wanted: StillWanted,
                                       settings: MitigationSettings,
                                       thresholds: AnomalyThresholds,
                                       incident_id: str | None = None,
                                       publisher: Publisher = nobody,
                                       onset: datetime | None = None) -> Verdict:
    """What the service did after the action, within the time allowed.

    Two questions rather than one, and which of them decides is read off the
    window rather than off the incident's mode. Where the minutes an incident is
    about were never published, the action was taken to restore the *sight* of the
    service, and what answers it is readings existing again - not readings sitting
    at a baseline, because a window nobody could read has no baseline to return to.
    Everywhere else the levels decide, exactly as they always have.

    The distinction is drawn over the span between the onset and the action, which
    is historical and settled by the time this runs. Asked of the minutes *after*
    the action instead it would answer the same for every incident on the first
    pass - no minute has finished yet - and asked of the window as a whole it would
    be overturned by the readings the action itself brought back, which arrive
    within the minute.

    An onset of `None` is every incident whose onset was measured rather than
    stated, and a measured onset means the window held a departure to measure it
    from. So the question does not arise there, and it is vacuous wherever an
    incident was dated and watched - silent data corruption among them, whose
    window carries every minute and merely holds them flat.

    `None` also means *nobody handed one over*, and the two are indistinguishable
    here by construction. That is safe only while every caller that has an onset
    passes it: `assembling.py` binds this function directly for exactly that
    reason, where the package's own `mitigate()` composes through `ActionTaker`,
    whose signature is one argument wide and deliberately carries no
    configuration. Route the walk through that instead and a blind spot would be
    judged on levels it does not have, with nothing anywhere saying so - which is
    the one way this parameter can fail quietly.

    `REFUTED` on expiry rather than an error, because that is a real answer
    about the world: the action was taken, the service was looked at, and it did
    not visibly help in the time it was given. Calling it an error would route an
    incident to a human over what is ordinary evidence against a hypothesis.

    `ESCALATED` where the window ran out with the service never once read. That
    is the same expiry and the opposite finding: the first is a measurement that
    went against the hypothesis, this is no measurement at all, and only one of
    them is evidence. They are separated on whether any reading ever landed
    rather than on how the last pass went, because a wait that read the shop
    nine times and failed on the tenth did measure it.

    `WITHDRAWN` where somebody stopped the walk while this was waiting. The loop
    already wakes every ten seconds to re-read the metrics, so asking here costs
    nothing and ends the wait within one interval of the withdrawal rather than
    at the end of a window nobody is waiting for.

    Each look is published. This is the one stretch of an incident where Argus
    is doing something and has nothing to show for it yet, and a page that went
    quiet here would read as a page that had stopped.
    """
    started_at = now()
    deadline = started_at + timedelta(
        seconds=settings.mitigation_verification_timeout_seconds
    )
    # The first minute that began after the action. The minute the action fell
    # inside is aggregated over seconds either side of it and can only blur the
    # two states together.
    first_whole_minute = to_iso_minute(started_at + timedelta(minutes=1))

    def say(
        event: AwaitingRecovery | RecoveryChecked | RetrievalUnanswered
    ) -> None:
        """Narrates the wait, where there is an incident to narrate it for."""
        if incident_id is not None:
            publish(event, publisher)

    if incident_id is not None:
        say(AwaitingRecovery(
            incident_id=incident_id,
            from_minute=first_whole_minute,
            seconds_allowed=settings.mitigation_verification_timeout_seconds,
        ))

    # Whether the service was ever actually looked at. What the expiry below
    # means depends entirely on it: a window that ran out having read the shop
    # and found it still bad is a refutation, and a window that ran out having
    # read nothing is not a verdict at all.
    anything_was_read = False
    # Whether this incident's own minutes were ever published, which decides which
    # of the two questions above is asked. `None` until a read answers, because it
    # is measured from a window rather than declared by a caller.
    the_sight_was_absent: bool | None = None

    while True:
        # A read that cannot be taken costs this pass and nothing more. The loop
        # is already a poll against a deadline, so a reading that did not arrive
        # is the one kind of failure it is built to absorb - and the alternative
        # was the whole incident: nothing above this catches it, so the walk
        # stopped mid-action, no verdict was recorded, and the incident kept
        # whatever status it was walking under.
        try:
            buckets = fetch_metrics()
        except Exception as unanswered:
            if incident_id is not None:
                say(RetrievalUnanswered(
                    incident_id=incident_id,
                    what_was_asked="the service's metrics",
                    because=str(unanswered),
                    minute=first_whole_minute
                ))

            # The deadline still decides, and it is checked before sleeping for
            # the reason the recovered case checks it: a window that has run out
            # must not buy another interval by having failed rather than
            # answered.
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
            if now() >= deadline:
                return Verdict.REFUTED if anything_was_read else Verdict.ESCALATED

            sleep(_SECONDS_BETWEEN_METRIC_READS)
            continue

        anything_was_read = True
        # Measured on the first pass that answered and not revisited: the span it
        # asks about ended when the action was taken, so a later pass would be
        # answering about a window the action itself has already changed.
        if the_sight_was_absent is None:
            the_sight_was_absent = _nothing_was_seen_between(
                buckets, onset, first_whole_minute
            )

        if the_sight_was_absent and has_a_reading_since(buckets, first_whole_minute):
            return Verdict.CONFIRMED

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
        came_back_at = find_recovery(buckets, thresholds) if recovered else None

        if incident_id is not None:
            say(RecoveryChecked(
                incident_id=incident_id,
                minute=first_whole_minute,
                recovered=recovered,
                recovered_minute=came_back_at
            ))

        # Asked before the recovery is acted on, and it outranks it: an incident
        # somebody took back is over whichever way this minute reads, and
        # claiming a confirmation on the pass the walk was stopped would credit
        # Argus with an ending it did not reach.
        if not still_wanted():
            return Verdict.WITHDRAWN

        if recovered:
            return Verdict.CONFIRMED

        if now() >= deadline:
            return Verdict.REFUTED

        sleep(_SECONDS_BETWEEN_METRIC_READS)


def _nothing_was_seen_between(buckets: Sequence[MetricBucket],
                              onset: datetime | None,
                              first_whole_minute: str) -> bool:
    """Whether the incident ran its course with none of it published.

    The minutes from the onset up to the action, asked of the readings that
    describe them. An incident anybody could watch has those minutes - they are
    what its onset was measured from - and one nobody could watch has none of
    them, which is the whole of what a monitoring blind spot is.

    False for an undated incident rather than unknown. An onset arrives here only
    where an alert stated one, and a stated onset is the only kind this question
    can be asked about: a measured one was derived from minutes that therefore
    exist.
    """
    if onset is None:
        return False

    return not has_a_reading_since(
        [bucket for bucket in buckets if bucket.bucket_id < first_whole_minute],
        to_iso_minute(onset)
    )


def _undone(performed: Performed, undo: UndoChange) -> Outcome:
    """Puts a refuted action back, and says so as a verdict.

    A refuted action was taken on a hypothesis the evidence has not borne out,
    so leaving its change in place would mean production state was altered for
    a cause that was not the cause, with nobody told.

    An action that left nothing behind is refuted with nothing to undo, and the
    account says so. Not "the undo failed" and not silence: a restart that did
    not help is a hypothesis refuted cleanly, and a reader has to be able to
    tell that from a flag Argus could not put back.

    The undo itself is `undo_change`; what this adds is what a *verdict* is
    made of. A change left as found is still a refutation - the service did not
    recover, which is what the verdict is about - while a change nobody could
    account for escalates, because an environment Argus cannot describe is
    precisely what a human needs paging for.
    """
    taken = performed.said
    undo_descriptor = performed.undo_descriptor

    if undo_descriptor is None:
        return Outcome(
            verdict=Verdict.REFUTED,
            detail=(
                f"{taken}, the service did not recover, and there was nothing "
                f"to put back"
            ),
        )

    attempt = undo(undo_descriptor)

    if attempt.outcome is Undone.NOT_ESTABLISHED:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"{taken}, the service did not recover, and {attempt.detail}",
            undo_descriptor=undo_descriptor,
        )

    if attempt.outcome is Undone.LEFT_AS_FOUND:
        return Outcome(
            verdict=Verdict.REFUTED,
            detail=f"{taken}, the service did not recover, and {attempt.detail}",
            undo_descriptor=undo_descriptor,
        )

    return Outcome(
        verdict=Verdict.REFUTED,
        detail=(
            f"{taken}, the service did not recover, so it was put back "
            f"{_how_it_was_put_back(undo_descriptor)}"
        ),
        undo_descriptor=undo_descriptor,
    )
