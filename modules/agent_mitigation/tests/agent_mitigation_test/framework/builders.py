from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from unittest.mock import MagicMock, create_autospec

from agent_mitigation import Action, Outcome, RevertFeatureFlag, UndoAttempt, Verdict
from agent_mitigation.tools import (
    AutoscalerPinner,
    AutoscalingRestorer,
    CacheEntryDiscarder,
    CapacityRestorer,
    ChangedFromOutside,
    DeploymentRestorer,
    DeploymentRoller,
    DeploymentScaler,
    FlagSetter,
    MetricsFetcher,
    PerformingWrites,
    ServiceRestarter,
    StillWanted,
)
from agent_mitigation.trying import UndoChange
from agent_mitigation.undoing import undo_change
from argus_core import to_iso_minute
from argus_core.models import (
    CacheEntriesDiscarded,
    ChangeEvent,
    ChangeKind,
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    MetricBucket,
    RestartedService,
    RestartService,
    UndoDescriptor,
    Undone,
)

DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_INCIDENT_ID = "3f0c6a8e-6f1e-4a9a-8c3d-2b7f9d1e5a44"
DONT_CARE_ACTOR = "dont-care-actor"

WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
CALM_MINUTES = 6
FAILING_MINUTES = 5
ACTION_TIME = WINDOW_START + timedelta(minutes=CALM_MINUTES + FAILING_MINUTES - 1, seconds=30)

EARLIER_IN_THE_WINDOW = "2026-08-20T11:02:00Z"
LATER_IN_THE_WINDOW = "2026-08-20T11:05:00Z"

CALM_RATE = 0.01
# The minute a blind spot began: the first one that carries no reading, which is
# the minute after the last one that does. Stated by the alert rather than
# measured, because the minutes that would carry a departure are the missing ones.
THE_ONSET = WINDOW_START + timedelta(minutes=CALM_MINUTES)
FAILING_RATE = CALM_RATE * 30
CALM_P50_MS = 80
CALM_P95_MS = 200
CALM_P99_MS = 350

# What the shop's heap sits at when nothing is accumulating, and where a leak
# has taken it by the time the incident is visible. Three times rather than a
# few percent: the departure rule works in units of the baseline's own spread,
# and a climb that has to be argued about is a different test from this one.
CALM_MEMORY_BYTES = 440 * 1024**2
LEAKING_MEMORY_BYTES = CALM_MEMORY_BYTES * 3


def an_undo_descriptor_for(flag: str,
                           was_enabled: bool = True,
                           written_at: datetime = ACTION_TIME) -> UndoDescriptor:
    return FlagUndo(
        flag=flag,
        was_enabled=was_enabled,
        environment="production",
        written_at=written_at
    )


def a_hypothesis_blaming(failure_mode: FailureMode,
                         subject: str | None = None,
                         faulting_service: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary=f"dont care - {failure_mode}",
        failure_mode=failure_mode,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject,
        faulting_service=faulting_service
    )


def an_undetermined_hypothesis() -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary="no cause determined",
        failure_mode=None,
        confidence=None,
        supporting_evidence=[]
    )


def an_enabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=at, actor=DONT_CARE_ACTOR)


def a_disabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=False, occurred_at=at, actor=DONT_CARE_ACTOR)


def a_deployment(actor: str | None = None) -> ChangeEvent:
    """A revision the platform recorded going out.

    Nothing that reads it here asks which revision or when - only that one is
    there, that the one reported is the one that came back, or who asked for it.
    """
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=LATER_IN_THE_WINDOW,
        reference="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
        summary="dont-care-summary",
        actor=actor
    )


def an_action_setting(flag: str, enabled: bool) -> Action:
    return RevertFeatureFlag(
        flag=flag,
        enabled=enabled,
        undo_descriptor=FlagUndo(flag=flag, was_enabled=not enabled)
    )


def an_action_restarting(service: str) -> Action:
    """The other kind, which carries no way back and has no field for one."""
    return RestartService(service=service)


def an_outcome_reaching(verdict: Verdict) -> Outcome:
    return Outcome(verdict=verdict, detail="dont care")


def a_clock_frozen_at(moment: datetime) -> Callable[[], datetime]:
    """A clock that never reaches any deadline, so a test decides how many
    looks the verification gets by what the metrics say, not by time."""
    return lambda: moment


def a_clock_that_runs_out_after_one_look(moment: datetime) -> Callable[[], datetime]:
    """Reads the action's own instant first, then an hour later - past any
    verification timeout a sane configuration allows."""
    readings = iter([moment])

    def clock() -> datetime:
        return next(readings, moment + timedelta(hours=1))

    return clock


def a_clock_reading_at(start: datetime,
                       *seconds_later: float) -> Callable[[], datetime]:
    """A clock reading `start` first, then each moment that many seconds after
    it, and sticking at the last.

    How a test says when each pass of a wait happened. Offsets rather than
    instants because what the cases here are about is the distance from the
    action - "past the configured wait, inside the one the service's own rhythm
    asks for" is the claim, and written as two timestamps it is a claim the reader
    has to do the arithmetic to see.

    Sticking rather than running out, so a loop that asks once more than the test
    expected gets an answer rather than a `StopIteration` raised three frames
    inside the thing under test.
    """
    moments = [start] + [
        start + timedelta(seconds=offset) for offset in seconds_later
    ]
    readings = iter(moments)

    def clock() -> datetime:
        return next(readings, moments[-1])

    return clock


def metrics_reading(window: list[MetricBucket]) -> MetricsFetcher:
    """A read of the service answering with one window, whichever rule it was
    read for - the rule decides which series the read tier adds, and the window
    a test hands in already says which it carries."""
    def read(dont_care_rule: str | None, /) -> list[MetricBucket]:
        return window

    return read


def dont_care_restart() -> ServiceRestarter:
    """The restart seam for a test about flags, which must never reach it.

    `take_action` takes a restarter whichever kind of action it is given, so
    every flag test has to pass one. Raising rather than returning says which:
    a test that reaches this is not the test it says it is.
    """
    def restart(service: str, /) -> RestartedService:
        raise AssertionError(f"No restart expected here, and {service} was asked for.")

    return restart


def a_window_ending_at_the_action() -> list[MetricBucket]:
    """Calm, then failing, and nothing after the action - the minute it fell
    inside is still in progress."""
    return a_window_of([CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * FAILING_MINUTES)


def a_window_that_never_departed() -> list[MetricBucket]:
    """Calm throughout, with no departure anywhere in it.

    What a stated-onset incident looks like to a rule watching a series: the
    shop is serving, the figures are wrong, and nothing in any of the five
    signals moved. There is no onset in here to find and no recovery to measure
    - which is the whole difficulty, because a window with nothing in it reads
    as a window with nothing wrong.
    """
    return a_window_of([CALM_RATE] * (CALM_MINUTES + FAILING_MINUTES + 2))


def a_recovered_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * FAILING_MINUTES + [CALM_RATE] * 2
    )


def a_window_recovered_before_the_action() -> list[MetricBucket]:
    """Calm, a departure just long enough to be a state, and calm again from
    well before the action.

    A service that came back on its own. The failing minutes end at 11:07 and
    the action's first whole minute is 11:11, so the minute the metrics date the
    recovery at sits three minutes before the minute the verdict is read from -
    which is the only shape that tells the two apart. `a_recovered_window` cannot:
    it comes back at 11:11, the action's own minute, so both answers are the same
    string and a test on it would pass against either rule.
    """
    minutes_it_failed_for = 2
    minutes_well_again = 5

    return a_window_of(
        [CALM_RATE] * CALM_MINUTES
        + [FAILING_RATE] * minutes_it_failed_for
        + [CALM_RATE] * minutes_well_again
    )


def a_still_failing_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * (FAILING_MINUTES + 2)
    )


def a_window_that_keeps_flapping() -> list[MetricBucket]:
    """A service departing one minute in five and never persisting.

    The window no picked wait can be right about. Every departure here is a
    single minute, so nothing in it stays departed long enough to give the
    incident a level, and the four clear minutes between departures occur twice -
    which is what makes them a rhythm rather than a recovery. One clear minute
    proves nothing about this service: it has twice been exactly that well and
    gone back.

    Two whole cycles and then a third departure, because a gap has to recur
    before it may be read at all. One cycle is a window asking for a single clear
    minute, which is this shape with the flap taken out of it.
    """
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES
        + [FAILING_RATE, CALM_RATE, CALM_RATE, CALM_RATE, CALM_RATE] * 2
        + [FAILING_RATE]
    )


def a_window_where_memory_was_reclaimed() -> list[MetricBucket]:
    """A leak, and then a restart that actually happened.

    The heap climbed with the incident and is back at the baseline after the
    action, which is what a new process looks like from the outside.
    """
    return a_window_of(
        error_rates=[CALM_RATE] * CALM_MINUTES
        + [FAILING_RATE] * FAILING_MINUTES
        + [CALM_RATE] * 2,
        memory_bytes=[CALM_MEMORY_BYTES] * CALM_MINUTES
        + [LEAKING_MEMORY_BYTES] * FAILING_MINUTES
        + [CALM_MEMORY_BYTES] * 2
    )


def a_window_where_memory_never_fell() -> list[MetricBucket]:
    """A leak whose symptoms eased and whose heap did not.

    The window a restart that was accepted and never happened produces: the
    traffic that was failing has moved on, so errors and latency read healthy
    again, while the process that has been accumulating since before the
    incident is still the process serving. Judged on symptoms alone this
    confirms; judged on all three signals it does not.
    """
    return a_window_of(
        error_rates=[CALM_RATE] * CALM_MINUTES
        + [FAILING_RATE] * FAILING_MINUTES
        + [CALM_RATE] * 2,
        memory_bytes=[CALM_MEMORY_BYTES] * CALM_MINUTES
        + [LEAKING_MEMORY_BYTES] * (FAILING_MINUTES + 2)
    )


def a_window_of(error_rates: list[float],
                memory_bytes: list[int] | None = None) -> list[MetricBucket]:
    """A window whose minutes read as the rates given, one minute each.

    Memory is flat at the baseline unless a caller says otherwise, because most
    windows here are flag scenarios: the fault moves the error rate and leaves
    the shop's heap where it was. A leak is the case that has to say otherwise,
    and it says so by handing a reading per minute.
    """
    dont_care_volume = 1000
    dont_care_started_at = WINDOW_START.timestamp()
    memory = memory_bytes or [CALM_MEMORY_BYTES] * len(error_rates)

    return [
        MetricBucket(
            bucket_id=to_iso_minute(WINDOW_START + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            p99_ms=CALM_P99_MS,
            request_volume=dont_care_volume,
            memory_used_bytes=memory_used,
            process_start_time_seconds=dont_care_started_at,
            cpu_used_cores=0.77,
            cpu_limit_cores=3.0
        )
        for offset, (error_rate, memory_used) in enumerate(
            zip(error_rates, memory, strict=True)
        )
    ]


def a_window_of_minutes(readings: dict[int, float]) -> list[MetricBucket]:
    """A window with only the minutes named in it, keyed by offset from the start.

    The other window builders take a rate per consecutive minute, which cannot
    express a window with a hole in it - and a hole is the whole of what a
    monitoring blind spot looks like from here. So the minutes are given by offset
    and the ones left out are genuinely absent, rather than present at zero.
    """
    return [
        bucket
        for offset, bucket in enumerate(
            a_window_of([readings.get(minute, 0.0) for minute in range(max(readings) + 1)])
        )
        if offset in readings
    ]


def a_window_that_stops_at_the_onset() -> list[MetricBucket]:
    """Calm minutes, and then nothing at all - the rows simply stop.

    Every minute from the onset onwards is missing, the action included, so
    nothing in this window says anything about the service after the onset. It is
    not a service that was watched and stayed bad; it is a service nobody saw.
    """
    return a_window_of_minutes({minute: CALM_RATE for minute in range(CALM_MINUTES)})


def a_window_whose_readings_return_at(rate: float) -> list[MetricBucket]:
    """Calm minutes, a dark stretch over the incident, and readings again after.

    The two minutes at the end are the first anybody has seen since the onset,
    which is what a restored telemetry pipeline looks like from the outside. The
    rate they carry is the caller's, because the whole question is whether the
    verdict turns on it.
    """
    returned = CALM_MINUTES + FAILING_MINUTES
    return a_window_of_minutes(
        {minute: CALM_RATE for minute in range(CALM_MINUTES)}
        | {returned: rate, returned + 1: rate}
    )


def nobody_wants_it_any_more() -> StillWanted:
    """A walk somebody stopped while it was waiting."""
    def still_wanted() -> bool:
        return False

    return still_wanted


def nobody_changed_it() -> ChangedFromOutside:
    """The provider's record shows nothing after Argus's own write."""
    def changed_from_outside(_flag: str, _since: datetime) -> bool | None:
        return False

    return changed_from_outside


def somebody_changed_it() -> ChangedFromOutside:
    """Somebody other than Argus is recorded as having changed the flag since.

    What the flag currently reads is deliberately not part of this: it may well
    still read as what Argus wrote, because the provider evaluates from a cache
    and the change that matters is the newest thing there is.
    """
    def changed_from_outside(_flag: str, _since: datetime) -> bool | None:
        return True

    return changed_from_outside


def nobody_can_say() -> ChangedFromOutside:
    """The provider could not be asked, so neither answer is available."""
    def changed_from_outside(_flag: str, _since: datetime) -> bool | None:
        return None

    return changed_from_outside


def a_restorer_nobody_calls() -> MagicMock:
    """The way back from a rollback, wired but not exercised.

    Required for the same reason the roller is: an agent that could be built
    without a way to undo an action it may take is an agent that finds out at
    the worst moment - when a refuted change is waiting to be put back.
    """
    restore: MagicMock = create_autospec(DeploymentRestorer, instance=True)

    return restore


def a_capacity_restorer_nobody_calls() -> MagicMock:
    """The way back from a scale-out, wired but not exercised.

    Required for the reason the deployment restorer is: an undo that could be
    built without a way back from every kind of change Argus makes is one that
    finds out at the worst moment, with a refuted change waiting to be put back.
    """
    restore: MagicMock = create_autospec(CapacityRestorer, instance=True)

    return restore


def an_autoscaling_restorer_nobody_calls() -> MagicMock:
    """The way back from a pin, wired but not exercised.

    Required for the reason the capacity restorer is: an undo that could be built
    without a way back from every kind of change Argus makes is one that finds out
    at the worst moment, with a refuted change waiting to be put back.
    """
    restore: MagicMock = create_autospec(AutoscalingRestorer, instance=True)

    return restore


def the_writes(set_state: FlagSetter | None = None,
               restart: ServiceRestarter | None = None,
               roll_back: DeploymentRoller | None = None,
               scale_out: DeploymentScaler | None = None,
               pin: AutoscalerPinner | None = None,
               discard: CacheEntryDiscarder | None = None) -> PerformingWrites:
    """The writes that perform a mitigation, with stand-ins for the unnamed ones.

    Every member is required of the real bundle, because an agent that could be
    built without a way to do one of the things it may do is one that finds out at
    the worst moment. A case about one kind of action still has to supply the other
    four, and naming them at every call site said nothing about the case - so what
    is not named here is a spy nobody calls, and a case that quietly performed the
    wrong kind of action fails on a call to a mock it never wired.
    """
    return PerformingWrites(
        set_state=set_state if set_state is not None else create_autospec(
            FlagSetter, instance=True
        ),
        restart=restart if restart is not None else create_autospec(
            ServiceRestarter, instance=True
        ),
        roll_back=roll_back if roll_back is not None else create_autospec(
            DeploymentRoller, instance=True
        ),
        scale_out=scale_out if scale_out is not None else create_autospec(
            DeploymentScaler, instance=True
        ),
        pin=pin if pin is not None else create_autospec(
            AutoscalerPinner, instance=True
        ),
        discard=discard if discard is not None else create_autospec(
            CacheEntryDiscarder, instance=True
        )
    )


def a_discard_removing(entries: int) -> MagicMock:
    """A store answering that this many of the keys it was named existed.

    The figure is the store's and not the caller's, which is the whole reason a
    discard can be confirmed from its own answer. A stand-in echoing back the
    number of keys asked for would make every discard look complete, including
    the one that removed nothing.
    """
    discarding: MagicMock = create_autospec(CacheEntryDiscarder, instance=True)
    discarding.return_value = CacheEntriesDiscarded(discarded=entries)

    return discarding


def an_undo_nobody_calls() -> MagicMock:
    """The way back, wired but not exercised.

    For the cases about an action that was confirmed, withdrawn, or never taken at
    all - none of which put anything back. Required rather than defaulted on
    `take_action`, because the caller that has one always has one: the Orchestrator
    passes the binding its withdrawal path shares, and a default composed here
    would be a second assembly of an undo for a case to exercise instead of the one
    that runs.
    """
    undo: MagicMock = create_autospec(UndoChange, instance=True)

    return undo


def an_undo_that_put_it_back(subject: str = DONT_CARE_FLAG) -> MagicMock:
    """The way back, wired and answering as the real one does.

    For a case whose action is refuted rather than confirmed. There the walk
    does put the change back, so the undo is called and its answer is read -
    which `an_undo_nobody_calls` cannot serve, whatever its name suggests: an
    autospec with no answer configured returns a `MagicMock`, and until the
    outcome was matched exhaustively that mock reached the restore's own
    sentence and was narrated as a change written back.

    `RESTORED` because these cases are about what the watching saw, not about
    what the undo found. A case that is about the undo builds the real one.
    """
    undo: MagicMock = create_autospec(UndoChange, instance=True)
    undo.return_value = UndoAttempt(
        subject=subject,
        outcome=Undone.RESTORED,
        detail=f"flag [{subject}] was put back"
    )

    return undo


def an_undo_putting_flags_back(
    set_state: FlagSetter,
    changed_from_outside: ChangedFromOutside
) -> UndoChange:
    """The undo a flag's case needs: the real one, over the setter under test.

    `undo_change` itself rather than a mock of it, because what these cases are
    about is the conditional write it performs - that a flag nobody touched is put
    back and one somebody changed is left as found. A stand-in would assert only
    that something was called.

    The restorers are spies: no flag case reaches a deployment.
    """
    return partial(
        undo_change,
        changed_from_outside=changed_from_outside,
        set_state=set_state,
        restore_deployment=a_restorer_nobody_calls(),
        restore_capacity=a_capacity_restorer_nobody_calls(),
        restore_autoscaling=an_autoscaling_restorer_nobody_calls()
    )
