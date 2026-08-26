from __future__ import annotations

import pytest
from argus_core.config import Settings
from pydantic import ValidationError


@pytest.mark.unit
def test_a_max_log_window_narrower_than_the_derived_window_is_rejected() -> None:
    some_lookback_minutes = 30
    some_lookahead_minutes = 10
    some_metrics_window_minutes = 360
    too_narrow_max_window = some_lookback_minutes + some_lookahead_minutes - 1

    with pytest.raises(ValidationError, match="log_max_window_minutes"):
        Settings(
            log_initial_lookback_minutes=some_lookback_minutes,
            log_initial_lookahead_minutes=some_lookahead_minutes,
            log_max_window_minutes=too_narrow_max_window,
            metrics_window_minutes=some_metrics_window_minutes
        )


@pytest.mark.unit
def test_a_metrics_window_narrower_than_the_max_log_window_is_rejected() -> None:
    some_max_log_window_minutes = 180
    some_lookback_minutes = 30
    some_lookahead_minutes = 10
    too_narrow_metrics_window = some_max_log_window_minutes - 1


    with pytest.raises(ValidationError, match="metrics_window_minutes"):
        Settings(
            log_initial_lookback_minutes=some_lookback_minutes,
            log_initial_lookahead_minutes=some_lookahead_minutes,
            log_max_window_minutes=some_max_log_window_minutes,
            metrics_window_minutes=too_narrow_metrics_window
        )


@pytest.mark.unit
def test_a_max_log_window_exactly_matching_the_derived_window_is_accepted() -> None:
    some_lookback_minutes = 30
    some_lookahead_minutes = 10
    some_metrics_window_minutes = 360
    max_window_exactly_the_derived_window = some_lookback_minutes + some_lookahead_minutes

    Settings(
        log_initial_lookback_minutes=some_lookback_minutes,
        log_initial_lookahead_minutes=some_lookahead_minutes,
        log_max_window_minutes=max_window_exactly_the_derived_window,
        metrics_window_minutes=some_metrics_window_minutes,
    )

@pytest.mark.unit
def test_an_iteration_budget_below_two_is_rejected() -> None:
    # One iteration cannot widen: the schedule would have to start at the
    # initial lookback and end at the maximum span in a single entry.
    too_few_iterations = 1

    with pytest.raises(ValidationError, match="investigation_max_iterations"):
        Settings(investigation_max_iterations=too_few_iterations)


@pytest.mark.unit
def test_an_iteration_budget_of_exactly_two_is_accepted() -> None:
    fewest_iterations_that_can_widen = 2

    Settings(investigation_max_iterations=fewest_iterations_that_can_widen)


@pytest.mark.unit
def test_a_non_positive_deviation_count_is_rejected() -> None:
    # Zero deviations from baseline makes every minute anomalous, including
    # the calm ones the loop needs in order to have a baseline at all.
    a_deviation_count_that_flags_every_minute = 0.0

    with pytest.raises(ValidationError, match="anomaly_deviations_from_baseline"):
        Settings(anomaly_deviations_from_baseline=a_deviation_count_that_flags_every_minute)


@pytest.mark.unit
def test_a_non_positive_change_lookback_is_rejected() -> None:
    # A zero-length change window can contain no change, so the channel could
    # only ever report "nothing changed" - the answer it exists to stop Argus
    # giving for the wrong reason.
    a_change_lookback_that_can_hold_nothing = 0

    with pytest.raises(ValidationError, match="change_lookback_minutes"):
        Settings(change_lookback_minutes=a_change_lookback_that_can_hold_nothing)


@pytest.mark.unit
def test_a_change_lookback_no_wider_than_the_log_ceiling_is_rejected() -> None:
    # Change events exist to surface a cause the logs cannot reach. A change
    # window no wider than the log ceiling can only ever repeat what the log
    # window already showed.
    some_max_log_window_minutes = 180
    some_lookback_minutes = 30
    some_lookahead_minutes = 10
    some_metrics_window_minutes = 360
    too_narrow_change_lookback = some_max_log_window_minutes

    with pytest.raises(ValidationError, match="change_lookback_minutes"):
        Settings(
            log_initial_lookback_minutes=some_lookback_minutes,
            log_initial_lookahead_minutes=some_lookahead_minutes,
            log_max_window_minutes=some_max_log_window_minutes,
            metrics_window_minutes=some_metrics_window_minutes,
            change_lookback_minutes=too_narrow_change_lookback,
        )
