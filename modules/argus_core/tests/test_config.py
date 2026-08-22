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
