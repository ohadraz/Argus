from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_mitigation import Action, Outcome, Verdict
from agent_mitigation.tools import ChangedFromOutside, StillWanted
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso, to_iso_minute

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


def an_undo_descriptor_for(flag: str,
                           was_enabled: bool = True,
                           written_at: datetime = ACTION_TIME) -> dict[str, Any]:
    return {
        "tool": "set_feature_flag",
        "flag": flag,
        "environment": "production",
        "was_enabled": was_enabled,
        "written_at": to_iso(written_at)
    }


def a_hypothesis_blaming(cause_type: CauseType, subject: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary=f"dont care - {cause_type}",
        cause_type=cause_type,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject
    )


def an_undetermined_hypothesis() -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary="no cause determined",
        cause_type=None,
        confidence=None,
        supporting_evidence=[]
    )


def an_enabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=at, actor=DONT_CARE_ACTOR)


def a_disabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=False, occurred_at=at, actor=DONT_CARE_ACTOR)


def an_action_setting(flag: str, enabled: bool) -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=flag,
        enabled=enabled,
        undo_descriptor={
            "tool": "set_feature_flag",
            "flag": flag,
            "was_enabled": not enabled
        }
    )


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


def dont_care_sleep(seconds: float) -> None:
    return None


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


def a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    dont_care_volume = 1000

    return [
        MetricBucket(
            bucket_id=to_iso_minute(WINDOW_START + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            request_volume=dont_care_volume
        )
        for offset, error_rate in enumerate(error_rates)
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
