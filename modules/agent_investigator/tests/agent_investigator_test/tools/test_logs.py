from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator.retrieval import fetch_logs
from agent_investigator.tools import LOGS_TOOL
from argus_core.config import get_settings
from argus_core.models.transcript import ToolResult
from argus_core.timestamps import parse_iso, to_iso
from argus_testkit import Assertion, Scenario, all_of

from ..framework.assertions.tool_results import the_result_failed
from ..framework.builders.dispatcher import AN_ALERT_TIME, AN_ONSET, a_call_to, a_dispatcher

"""The log channel: the window the model asked for, and the one it did not.

The expensive channel and the only one with a ceiling, so this is where a
window is most likely to be wrong - too wide, inverted, or absent. None of
those may end the investigation: an inverted window is the model's mistake to
correct on its next turn, and a clamped one is only honest if the model is
told it was clamped.
"""


@pytest.mark.unit
def test_a_log_call_reads_the_window_the_model_named() -> None:
    # The point of the change. The model saw something in the metrics and
    # wants the minutes around it; a dispatcher that substituted its own
    # window would put the schedule back by another name.
    some_window_start = "2026-08-29T21:50:00Z"
    some_window_end = "2026-08-29T22:05:00Z"
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(
                a_call_to(LOGS_TOOL,
                          window_start=some_window_start,
                          window_end=some_window_end)
            )
        ) \
        .then(
            _the_logs_read_were(some_fetch_logs, some_window_start, some_window_end)
        )


@pytest.mark.unit
def test_a_log_call_naming_no_window_reads_from_before_the_onset_to_the_alert() -> None:
    # A window the model left to Argus still has to be the right one. It
    # starts before the onset because that is where a cause lands - a flag
    # flips in a minute that still looks healthy - and ends at the alert,
    # which is the one moment the service is known to have been unhealthy.
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])
    the_default_start = to_iso(
        parse_iso(AN_ONSET)
        - timedelta(minutes=get_settings().log_initial_lookback_minutes)
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(LOGS_TOOL))
        ) \
        .then(
            _the_logs_read_were(some_fetch_logs, the_default_start, AN_ALERT_TIME)
        )


@pytest.mark.unit
def test_a_log_call_reads_past_the_onset_when_the_alert_says_no_time() -> None:
    # An alert that never said when it started leaves the default window with
    # nothing to end on. It ends a few minutes after the onset instead of at
    # the onset itself, because a window ending the minute the incident began
    # contains the cause and none of the symptoms.
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])
    the_default_start = to_iso(
        parse_iso(AN_ONSET)
        - timedelta(minutes=get_settings().log_initial_lookback_minutes)
    )
    the_default_end = to_iso(
        parse_iso(AN_ONSET)
        + timedelta(minutes=get_settings().log_initial_lookahead_minutes)
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs, alert_time=None)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(LOGS_TOOL))
        ) \
        .then(
            _the_logs_read_were(some_fetch_logs, the_default_start, the_default_end)
        )


@pytest.mark.unit
def test_a_window_that_ends_before_it_starts_comes_back_as_something_to_fix() -> None:
    # The model's mistake to correct, not the end of the investigation. A
    # raised exception here would throw away every minute already read over a
    # typo the model could fix on its next turn.
    a_window_start = "2026-08-29T22:10:00Z"
    a_window_end_before_it = "2026-08-29T21:50:00Z"
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(
                a_call_to(LOGS_TOOL,
                          window_start=a_window_start,
                          window_end=a_window_end_before_it)
            )
        ) \
        .then(
            all_of(
                the_result_failed(),
                _nothing_was_read(some_fetch_logs)
            )
        )


@pytest.mark.unit
def test_a_window_wider_than_the_maximum_is_clamped_and_said_to_be() -> None:
    # Clamped at the start rather than the end, because the tail is the half
    # certainly inside the incident. Said to be clamped because a model that
    # asked for three hours and silently got one would read the absence of
    # evidence as evidence of absence.
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])
    a_window_end = AN_ALERT_TIME
    a_window_start_beyond_the_maximum = to_iso(
        parse_iso(a_window_end)
        - timedelta(minutes=get_settings().log_max_window_minutes * 2)
    )
    the_earliest_affordable_start = to_iso(
        parse_iso(a_window_end)
        - timedelta(minutes=get_settings().log_max_window_minutes)
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(
                a_call_to(LOGS_TOOL,
                          window_start=a_window_start_beyond_the_maximum,
                          window_end=a_window_end)
            )
        ) \
        .then(
            all_of(
                _the_logs_read_were(
                    some_fetch_logs, the_earliest_affordable_start, a_window_end
                ),
                _the_result_says_it_was_clamped()
            )
        )


def _the_logs_read_were(reader: Mock,
                        window_start: str,
                        window_end: str) -> Assertion[ToolResult]:
    """The window the log channel was actually asked for."""
    def assertion(dont_care_result: ToolResult) -> bool:
        reader.assert_called_once_with(window_start, window_end)

        return True

    return assertion


def _nothing_was_read(reader: Mock) -> Assertion[ToolResult]:
    """A request the dispatcher refused must not also have been served."""
    def assertion(dont_care_result: ToolResult) -> bool:
        reader.assert_not_called()

        return True

    return assertion


def _the_result_says_it_was_clamped() -> Assertion[ToolResult]:
    """A narrowed window the model was not told about is a silent lie."""
    def assertion(result: ToolResult) -> bool:
        if "clamp" not in result.content.lower():
            raise AssertionError(
                f"Expected the result to say the window was clamped, got [{result.content}]."
            )

        return True

    return assertion
