from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, create_autospec

from agent_mitigation import Action, Outcome, RevertFeatureFlag, Verdict
from agent_mitigation.tools import (
    ChangedFromOutside,
    ConfigurationRestorer,
    ServiceRestarter,
    StillWanted,
)
from argus_core import to_iso_minute
from argus_core.models import (
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    MetricBucket,
    RestartedService,
    RestartService,
    UndoDescriptor,
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


def a_hypothesis_blaming(failure_mode: FailureMode, subject: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary=f"dont care - {failure_mode}",
        failure_mode=failure_mode,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject
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


def metrics_reading(window: list[MetricBucket]) -> Callable[[], list[MetricBucket]]:
    return lambda: window


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


def a_recovered_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * FAILING_MINUTES + [CALM_RATE] * 2
    )


def a_still_failing_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * (FAILING_MINUTES + 2)
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
            process_start_time_seconds=dont_care_started_at
        )
        for offset, (error_rate, memory_used) in enumerate(
            zip(error_rates, memory, strict=True)
        )
    ]


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
    restore: MagicMock = create_autospec(ConfigurationRestorer, instance=True)

    return restore
