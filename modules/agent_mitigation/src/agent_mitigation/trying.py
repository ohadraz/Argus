"""Taking one proposed action, and judging what the service did (spec §7.3).

The mutating half of the agent. `actions.py` decides what to do without
touching anything; this performs it, waits for the service to answer, and puts
the change back where the answer refutes the hypothesis it was taken on.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import NamedTuple, Protocol, assert_never

from argus_core import sleep_on_the_clock, to_iso_minute, utc_now
from argus_core.anomaly import (
    AnomalyThresholds,
    find_recovery,
    has_a_departure_in_it,
    has_a_reading_since,
    has_recovered_since,
    minutes_a_recovery_must_hold,
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
    ActionType,
    AlertRuleStanding,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    FlagUndo,
    MetricBucket,
    PinAutoscaler,
    ReplicaUndo,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    UndoDescriptor,
    changes_something_persistent,
    reports_what_it_changed,
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
    Arrival,
    ArrivalFor,
    Clock,
    HasArrived,
    MetricsFetcher,
    MitigationSettings,
    PerformingWrites,
    RuleReader,
    Sleeper,
    StillWanted,
    nothing_to_wait_for,
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
                sleep: Sleeper = sleep_on_the_clock,
                still_wanted: StillWanted = _nobody_stopped_this_walk,
                arrivals: ArrivalFor = nothing_to_wait_for,
                incident_id: str | None = None,
                publisher: Publisher = nobody,
                *,
                onset: datetime | None = None,
                rule: str | None = None,
                read_rule: RuleReader | None = None,
                writes: PerformingWrites,
                undo: UndoChange) -> Outcome:
    """Performs `action` and answers with what the service then did (spec §7.3).

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
        # Read for the rule that paged, so the recovery is dated on its series.
        partial(fetch_metrics, rule), arrivals(action), now, sleep, still_wanted, settings,
        thresholds, action.action_type, incident_id, publisher, onset,
        read_the_rule=(
            partial(read_rule, rule)
            if rule is not None and read_rule is not None
            else None
        )
    )

    if settled.verdict is Verdict.CONFIRMED:
        return Outcome(
            verdict=Verdict.CONFIRMED,
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
            detail=f"{performed.said}, and {settled.because}",
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
    if settled.verdict is Verdict.WITHDRAWN:
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

    return _undone(performed, undo, action.action_type)


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
        case DiscardCacheEntries():
            discarded = writes.discard(action.keys)

            return Performed(
                said=(
                    # The store's figure and never the number of keys asked for.
                    # This is the one action confirmed from its own answer, so a
                    # sentence quoting what was requested would report a discard
                    # that removed nothing as one that removed everything - and
                    # nothing downstream watches a series that could contradict
                    # it.
                    f"discarded [{discarded.discarded}] of "
                    f"[{action.service}]'s stale cached figures"
                ),
                # The one action that changes something persistent and still
                # records no way back. A restart records none because it changed
                # nothing to record; this changed something and there is nothing
                # to restore, because the figures were a copy of records it never
                # touched. A descriptor here would promise to write the stale
                # values back, which is a promise to recreate the incident.
                undo_descriptor=None
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
        case DiscardCacheEntries():
            # Figures thrown away, never data deleted or a cache cleared. What
            # goes is a copy and the records behind it are untouched, so a verb
            # suggesting otherwise would describe an action a reader should be
            # alarmed by - in a line that exists to explain why Argus is *not*
            # doing it again.
            return f"discard [{action.service}]'s stale cached figures"
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


def _what_watching_the_service_settled(fetch_metrics: Callable[[], list[MetricBucket]],
                                       has_arrived: HasArrived,
                                       now: Clock,
                                       sleep: Sleeper,
                                       still_wanted: StillWanted,
                                       settings: MitigationSettings,
                                       thresholds: AnomalyThresholds,
                                       action_type: ActionType,
                                       incident_id: str | None = None,
                                       publisher: Publisher = nobody,
                                       onset: datetime | None = None,
                                       read_the_rule: (
                                           Callable[[], AlertRuleStanding] | None
                                       ) = None) -> _Settled:
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

    An onset of `None` is every incident whose onset was measured rather than
    stated, and a measured onset means the window held a departure to measure it
    from. So the question does not arise there, and it is vacuous wherever an
    incident was dated and watched - silent data corruption among them, whose
    window carries every minute and merely holds them flat.

    `None` also means *nobody handed one over*, and the two are indistinguishable
    here by construction. That is safe only while every caller that has an onset
    passes it: `assembling.py` binds this function directly for exactly that
    reason. Route the walk through a seam one argument wide instead and a blind
    spot would be judged on levels it does not have, with nothing anywhere saying
    so - which is the one way this parameter can fail quietly.

    How long it is given is read off the service's own window rather than
    configured - `_when_a_recovery_would_have_shown` - or, where the rule that
    paged judges, off the rule - `_when_the_rule_would_have_resolved`. A picked
    figure is wrong in both directions at once.

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
    # What bounds the stretch where nothing has been measured: the change still
    # arriving, or a service that will not answer a read. How long to *watch* is
    # read off the window below, and until a window has come back there is
    # nothing to read it off - the only facts are that an action was taken and
    # that nothing has answered, and a configured figure is all either of them
    # supports.
    nothing_measured_by = started_at + timedelta(
        seconds=settings.mitigation_verification_timeout_seconds
    )

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
    # Whether the rule that paged was ever read, which decides what running out
    # of time means on that path, as `anything_was_read` does on this one.
    the_rule_was_read = False

    while True:
        # A read that cannot be taken costs this pass and nothing more. The loop
        # is already a poll against a deadline, so a reading that did not arrive
        # is the one kind of failure it is built to absorb - and the alternative
        # was the whole incident: nothing above this catches it, so the walk
        # stopped mid-action, no verdict was recorded, and the incident kept
        # whatever status it was walking under.
        buckets: list[MetricBucket] | None
        try:
            buckets = fetch_metrics()
        except Exception as unanswered:
            buckets = None

            if incident_id is not None:
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
            if now() >= watch_until:
                return (
                    _Settled(
                        Verdict.REFUTED,
                        "it did not visibly help in the time it was given"
                    )
                    if anything_was_read else
                    _Settled(
                        Verdict.ESCALATED,
                        "the service could not be read once before the time "
                        "allowed ran out - so nothing was measured either way"
                    )
                )

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

            # Announced here rather than before the first read, because the
            # figure is measured off that window: said earlier it would be a
            # guess, and the page and the Slack line both say it aloud. A wait
            # whose reads never answer therefore announces nothing - what the
            # page carries then is a line per unanswered read, which is the same
            # thing this was there to prevent.
            if incident_id is not None:
                say(AwaitingRecovery(
                    incident_id=incident_id,
                    from_minute=first_whole_minute,
                    seconds_allowed=(watch_until - arrived_at).total_seconds()
                ))

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
            except Exception as unanswered:
                if incident_id is not None:
                    say(RetrievalUnanswered(
                        incident_id=incident_id,
                        what_was_asked="the alert rule that paged",
                        because=str(unanswered),
                        minute=first_whole_minute
                    ))

                # Not refuted where the rule was never read: nothing said it was
                # still firing, and refuting puts the change back on a
                # measurement nobody took.
                if now() >= watch_until:
                    return (
                        _Settled(
                            Verdict.REFUTED,
                            "the rule that paged was still firing when the time "
                            "it allows ran out"
                        )
                        if the_rule_was_read else
                        _Settled(
                            Verdict.ESCALATED,
                            "the rule that paged could not be read once before "
                            "the time allowed ran out - so nothing was measured "
                            "either way"
                        )
                    )

                sleep(_SECONDS_BETWEEN_METRIC_READS)
                continue

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
            # action had no part in.
            resolved = standing.is_normal and (
                standing.evaluated_at - timedelta(seconds=standing.range_seconds)
                >= arrived_at
            )
            came_back_at = find_recovery(buckets, thresholds) if resolved else None

            if incident_id is not None:
                say(RecoveryChecked(
                    incident_id=incident_id,
                    minute=first_whole_minute,
                    recovered=resolved,
                    recovered_minute=came_back_at
                ))

            if not still_wanted():
                return _Settled(
                    Verdict.WITHDRAWN,
                    "the incident was withdrawn before the service could answer"
                )

            if resolved:
                return _Settled(
                    Verdict.CONFIRMED, "the rule that paged stopped firing"
                )

            if now() >= watch_until:
                return _Settled(
                    Verdict.REFUTED,
                    "the rule that paged was still firing when the time it "
                    "allows ran out"
                )

            sleep(_SECONDS_BETWEEN_METRIC_READS)
            continue

        # Measured on the first pass that answered and not revisited: the span it
        # asks about ended when the action was taken, so a later pass would be
        # answering about a window the action itself has already changed.
        if the_sight_was_absent is None:
            the_sight_was_absent = _nothing_was_seen_between(
                buckets, onset, to_iso_minute(arrived_at)
            )

        if the_sight_was_absent and has_a_reading_since(buckets, first_whole_minute):
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
        if not departed and reports_what_it_changed(action_type):
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
                "improvement for it to show and this action answered for nothing"
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
            return _Settled(
                Verdict.WITHDRAWN,
                "the incident was withdrawn before the service could answer"
            )

        if recovered:
            return _Settled(
                Verdict.CONFIRMED, "the service returned to baseline"
            )

        if now() >= watch_until:
            return _Settled(
                Verdict.REFUTED,
                "it did not visibly help in the time it was given"
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
    """
    moment = started_at

    while True:
        arrival = has_arrived()

        if arrival is Arrival.ARRIVED:
            return moment

        if arrival is Arrival.WILL_NOT_ARRIVE:
            return _Settled(
                Verdict.ESCALATED,
                "the platform stopped applying the change, so it never applied "
                "and nothing about it was measured"
            )

        # Checked before sleeping for the reason every other wait here checks it
        # first: a window that has run out must not buy another interval by having
        # been busy.
        if moment >= no_later_than:
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

    This module's arithmetic rather than `argus_core`'s, because `argus_core` has
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
    since it arrived; the next evaluation sees that, and a rule that keeps firing
    for a while after its condition clears says so that much later. The source's
    lag is added for the reason the metrics' deadline adds it: the minutes the
    rule reads arrive `reporting_lag_minutes` late from a source that reports
    them once they end.

    Every term but the lag is the rule's own; the lag is the one setting, and
    the levels' deadline adds the same one.
    """
    return arrived_at + timedelta(
        seconds=(
            standing.range_seconds
            + standing.interval_seconds
            + standing.keep_firing_for_seconds
        ),
        minutes=reporting_lag_minutes
    )


def _nothing_was_seen_between(buckets: Sequence[MetricBucket],
                              onset: datetime | None,
                              acted_in_minute: str) -> bool:
    """Whether the incident ran its course with none of it published.

    The minutes from the onset up to the action, asked of the readings that
    describe them. An incident anybody could watch has those minutes - they are
    what its onset was measured from - and one nobody could watch has none of
    them, which is the whole of what a monitoring blind spot is.

    `acted_in_minute` is the minute the action itself fell inside, and the slice
    stops strictly before it. That minute is aggregated over seconds either side
    of the change, so it describes neither the service that was failing nor the
    one that was fixed - and where an action restores the sight, it is the first
    minute the rows come back in. Counted as evidence the sight was there, it
    answers this question with the very thing the action did about it, and the
    incident is then judged on levels whose absence was the incident.

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
            action_type: ActionType) -> Outcome:
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
                f"{taken}, the service did not recover, and "
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
            return Outcome(
                verdict=Verdict.ESCALATED,
                detail=f"{taken}, the service did not recover, and {attempt.detail}",
                undo_descriptor=undo_descriptor,
            )
        case Undone.LEFT_AS_FOUND:
            return Outcome(
                verdict=Verdict.REFUTED,
                detail=f"{taken}, the service did not recover, and {attempt.detail}",
                undo_descriptor=undo_descriptor,
            )
        case Undone.RESTORED:
            return Outcome(
                verdict=Verdict.REFUTED,
                detail=(
                    f"{taken}, the service did not recover, so it was put back "
                    f"{_how_it_was_put_back(undo_descriptor)}"
                ),
                undo_descriptor=undo_descriptor,
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
                detail=(
                    f"{taken}, the service did not recover, and "
                    f"{_why_nothing_was_put_back(action_type)}"
                ),
                undo_descriptor=undo_descriptor,
            )

    assert_never(attempt.outcome)
