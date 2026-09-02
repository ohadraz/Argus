from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_mitigation import take_action
from agent_mitigation.tools import set_flag
from argus_core.events import AwaitingRecovery, IncidentEvent, RecoveryChecked
from argus_core.ids import new_id
from argus_core.models.action import Action, Verdict
from argus_core.models.metrics import MetricBucket

"""The wait, narrated.

Everything else Argus does leaves a mark within a second or two of doing it.
Taking an action does not: the flag is set, and then nothing is published for
as long as it takes the service to answer - which is the longest silence on
the page and the one a viewer is most likely to read as nothing happening.
These say the wait is announced when it begins and reported on as it goes.
"""


@pytest.mark.unit
def test_the_wait_is_announced_when_the_action_has_been_taken() -> None:
    # The flag has moved by this point and production is in its new state. A
    # page that said nothing until a verdict arrived would leave a reader
    # unable to tell a slow verification from a stuck one.
    published: list[IncidentEvent] = []

    _an_action_is_taken(publisher=published.append, metrics=_a_recovered_window())

    announced = [event for event in published if isinstance(event, AwaitingRecovery)]
    assert len(announced) == 1, f"Expected one announcement, got {len(announced)}."


@pytest.mark.unit
def test_the_wait_says_which_minute_it_will_judge_from() -> None:
    # Not the minute the action fell inside: that one is aggregated over
    # seconds either side of the change and can only blur the two states
    # together. Saying which minute counts is what makes the wait checkable.
    published: list[IncidentEvent] = []

    _an_action_is_taken(publisher=published.append, metrics=_a_recovered_window())

    announced = next(event for event in published if isinstance(event, AwaitingRecovery))
    assert announced.from_minute == _THE_FIRST_WHOLE_MINUTE_AFTER


@pytest.mark.unit
def test_each_look_at_the_service_is_published_with_what_it_saw() -> None:
    # The narration of a wait is the looking, not the waiting - a line per
    # check is what turns a blank two minutes into a page that is visibly
    # working.
    published: list[IncidentEvent] = []

    _an_action_is_taken(publisher=published.append, metrics=_a_recovered_window())

    checked = [event for event in published if isinstance(event, RecoveryChecked)]
    assert [event.recovered for event in checked] == [True]


@pytest.mark.unit
def test_a_service_that_has_not_recovered_yet_is_published_as_not_recovered() -> None:
    # "Checked, and it is still bad" is the ordinary case for most of a wait,
    # and reporting only recovery would make a refuted action's whole
    # verification invisible.
    published: list[IncidentEvent] = []

    _an_action_is_taken(
        publisher=published.append,
        metrics=_a_still_failing_window(),
        clock=_a_clock_that_runs_out_after_one_look(),
    )

    checked = [event for event in published if isinstance(event, RecoveryChecked)]
    assert [event.recovered for event in checked] == [False]


@pytest.mark.unit
def test_an_action_taken_outside_an_incident_narrates_nothing() -> None:
    # `Action` is not incident-scoped and nor is this call. An action taken
    # without one is not an error; it is an action with nothing to attribute
    # its story to, and inventing an incident to hang it on would be worse.
    published: list[IncidentEvent] = []

    _an_action_is_taken(
        publisher=published.append, metrics=_a_recovered_window(), incident_id=None
    )

    assert published == []


@pytest.mark.unit
def test_the_verdict_is_the_same_whether_or_not_anybody_is_listening() -> None:
    # The account is never part of the work, here as everywhere else.
    listened_to = _an_action_is_taken(
        publisher=[].append, metrics=_a_recovered_window()
    )
    unheard = _an_action_is_taken(metrics=_a_recovered_window())

    assert listened_to.verdict is unheard.verdict is Verdict.CONFIRMED


_WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
_CALM_MINUTES = 6
_FAILING_MINUTES = 5
_ACTION_TIME = _WINDOW_START + timedelta(
    minutes=_CALM_MINUTES + _FAILING_MINUTES - 1, seconds=30
)
_THE_FIRST_WHOLE_MINUTE_AFTER = "2026-08-20T11:11:00Z"
_CALM_RATE = 0.01
_FAILING_RATE = _CALM_RATE * 30
_SOME_INCIDENT_ID = new_id()
_DONT_CARE_FLAG = "monthly-spend-feature"


def _an_action_is_taken(metrics: list[MetricBucket],
                        publisher: Any = None,
                        clock: Callable[[], datetime] | None = None,
                        incident_id: str | None = _SOME_INCIDENT_ID) -> Any:
    keywords = {"publisher": publisher} if publisher is not None else {}

    return take_action(
        Action(
            action_type="revert-feature-flag",
            flag=_DONT_CARE_FLAG,
            enabled=False,
            undo_descriptor={"flag": _DONT_CARE_FLAG, "was_enabled": True},
        ),
        incident_id=incident_id,
        set_state=_a_write_tier(),
        fetch_metrics=lambda: metrics,
        now=clock or (lambda: _ACTION_TIME),
        sleep=lambda dont_care_seconds: None,
        **keywords,
    )


def _a_write_tier() -> Any:
    """The write tier, answering with the descriptor that undoes the change.

    `create_autospec` on a plain function gives back a function object with
    tracking attached rather than a `MagicMock`, so the return value is set on
    it directly - and it has to be set, because the real `set_flag` answers
    with the undo descriptor and an `Outcome` refuses anything else.
    """
    setter = create_autospec(set_flag)
    setter.return_value = {"flag": _DONT_CARE_FLAG, "was_enabled": True}

    return setter


def _a_clock_that_runs_out_after_one_look() -> Callable[[], datetime]:
    """The action's own instant first, then an hour later - past any
    verification timeout a sane configuration allows."""
    readings = iter([_ACTION_TIME])

    return lambda: next(readings, _ACTION_TIME + timedelta(hours=1))


def _a_recovered_window() -> list[MetricBucket]:
    return _a_window_of(
        [_CALM_RATE] * _CALM_MINUTES
        + [_FAILING_RATE] * _FAILING_MINUTES
        + [_CALM_RATE] * 2
    )


def _a_still_failing_window() -> list[MetricBucket]:
    return _a_window_of(
        [_CALM_RATE] * _CALM_MINUTES + [_FAILING_RATE] * (_FAILING_MINUTES + 2)
    )


def _a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    dont_care_volume = 1000

    return [
        MetricBucket(
            bucket_id=(_WINDOW_START + timedelta(minutes=offset)).strftime(
                "%Y-%m-%dT%H:%M:00Z"
            ),
            error_rate=error_rate,
            p50_ms=80,
            p95_ms=200,
            request_volume=dont_care_volume,
        )
        for offset, error_rate in enumerate(error_rates)
    ]
