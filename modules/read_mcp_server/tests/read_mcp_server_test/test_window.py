"""Which minutes a retrieval actually reads, given what the caller asked for.

Two resolvers rather than one, because the two channels have different ceilings
and the difference is the point: log lines are millions where metric buckets are
a handful, so a span the log phase refuses is ordinary for metrics. A single
resolver with a parameter would make that a caller's decision rather than a
property of the channel.

Nothing here retrieves anything. These are the arithmetic - a default, a
ceiling, an anchor - and they are asserted on their own so that a window being
wrong is not something to be inferred from what came back.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from argus_testkit import Assertion, Scenario, all_of
from read_mcp_server.window import (
    ResolvedWindow,
    RetrievalSettings,
    resolve_log_window,
    resolve_metrics_window,
)

from read_mcp_server_test.framework.timestamps import an_iso_minute

MINUTES_IN_A_DAY = 24 * 60

# The windows these resolve against, stated here rather than read from the
# environment. Every expectation below is arithmetic on these four numbers,
# and a test that took them from the same configuration the resolver reads
# would agree with itself whatever either said.
CONFIGURED_WINDOWS = RetrievalSettings(
    log_initial_lookback_minutes=30,
    log_initial_lookahead_minutes=10,
    log_max_window_minutes=180,
    metrics_window_minutes=360
)


@pytest.mark.unit
def test_no_alert_time_and_no_window_resolves_to_no_window() -> None:
    Scenario() \
        .when(
            lambda: resolve_log_window(settings=CONFIGURED_WINDOWS)
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(start=None, end=None, clamped=False))
        )


@pytest.mark.unit
def test_a_log_window_spans_the_configured_lookback_and_lookahead() -> None:
    Scenario() \
        .given(
            some_alert_time := _an_alert_time()
        ) \
        .when(
            lambda: resolve_log_window(
                alert_time=an_iso_minute(some_alert_time),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_alert_time - timedelta(
                    minutes=CONFIGURED_WINDOWS.log_initial_lookback_minutes
                ),
                end=some_alert_time + timedelta(
                    minutes=CONFIGURED_WINDOWS.log_initial_lookahead_minutes
                ),
                clamped=False
            ))
        )


@pytest.mark.unit
def test_a_log_window_whose_lookahead_runs_past_now_ends_at_now() -> None:
    too_recent_alert = _a_minute_ago(CONFIGURED_WINDOWS.log_initial_lookahead_minutes - 1)
    lookahead_in_the_future = too_recent_alert + timedelta(
        minutes=CONFIGURED_WINDOWS.log_initial_lookahead_minutes
    )

    # `now` advances while the test runs, so the assertions are on the bound
    # rather than on an instant: the end stopped short of the full lookahead,
    # and did not overshoot into the future. Stopping at "now" is not the span
    # clamp, so there is nothing to warn the caller about.
    Scenario() \
        .given(
            too_recent_alert, lookahead_in_the_future
        ) \
        .when(
            lambda: resolve_log_window(
                alert_time=an_iso_minute(too_recent_alert),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(all_of(
            _the_window_ended_before(lookahead_in_the_future),
            _the_window_ended_no_later_than_now(),
            _the_window_was_not_clamped()
        ))


@pytest.mark.unit
def test_an_explicit_log_window_exactly_on_the_ceiling_is_used_as_given() -> None:
    some_window_start = _an_alert_time()
    window_end_exactly_on_the_ceiling = some_window_start + timedelta(
        minutes=CONFIGURED_WINDOWS.log_max_window_minutes
    )

    Scenario() \
        .given(
            some_window_start, window_end_exactly_on_the_ceiling
        ) \
        .when(
            lambda: resolve_log_window(
                window_start=an_iso_minute(some_window_start),
                window_end=an_iso_minute(window_end_exactly_on_the_ceiling),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_start,
                end=window_end_exactly_on_the_ceiling,
                clamped=False
            ))
        )


@pytest.mark.unit
def test_an_explicit_window_overrides_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_unrelated_window_start = some_alert_time - timedelta(days=1)
    some_unrelated_window_end = some_unrelated_window_start + timedelta(minutes=1)

    Scenario() \
        .given(
            some_alert_time, some_unrelated_window_start, some_unrelated_window_end
        ) \
        .when(
            lambda: resolve_log_window(
                alert_time=an_iso_minute(some_alert_time),
                window_start=an_iso_minute(some_unrelated_window_start),
                window_end=an_iso_minute(some_unrelated_window_end),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_unrelated_window_start,
                end=some_unrelated_window_end,
                clamped=False
            ))
        )


@pytest.mark.unit
def test_an_over_span_log_window_is_clamped_forward_from_its_start() -> None:
    some_window_start = _an_alert_time()
    window_end_past_the_ceiling = some_window_start + timedelta(
        minutes=CONFIGURED_WINDOWS.log_max_window_minutes + 1
    )

    # Anchored at the start: the earliest minutes are the ones that explain
    # onset, so an over-wide request loses its tail, never its head.
    Scenario() \
        .given(
            some_window_start, window_end_past_the_ceiling
        ) \
        .when(
            lambda: resolve_log_window(
                window_start=an_iso_minute(some_window_start),
                window_end=an_iso_minute(window_end_past_the_ceiling),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_start,
                end=some_window_start + timedelta(
                    minutes=CONFIGURED_WINDOWS.log_max_window_minutes
                ),
                clamped=True
            ))
        )


@pytest.mark.unit
def test_a_log_window_with_only_a_start_is_clamped_forward_from_it() -> None:
    Scenario() \
        .given(
            some_window_start := _an_alert_time()
        ) \
        .when(
            lambda: resolve_log_window(
                window_start=an_iso_minute(some_window_start),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_start,
                end=some_window_start + timedelta(
                    minutes=CONFIGURED_WINDOWS.log_max_window_minutes
                ),
                clamped=True
            ))
        )


@pytest.mark.unit
def test_a_log_window_with_only_an_end_is_clamped_back_from_it() -> None:
    Scenario() \
        .given(
            some_window_end := _an_alert_time()
        ) \
        .when(
            lambda: resolve_log_window(
                window_end=an_iso_minute(some_window_end),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_end - timedelta(
                    minutes=CONFIGURED_WINDOWS.log_max_window_minutes
                ),
                end=some_window_end,
                clamped=True
            ))
        )


@pytest.mark.unit
def test_a_metrics_window_spans_the_metrics_window_on_both_sides_of_the_alert() -> None:
    some_alert_time = _an_alert_time()
    metrics_window = timedelta(minutes=CONFIGURED_WINDOWS.metrics_window_minutes)

    Scenario() \
        .given(
            some_alert_time, metrics_window
        ) \
        .when(
            lambda: resolve_metrics_window(
                alert_time=an_iso_minute(some_alert_time),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_alert_time - metrics_window,
                end=some_alert_time + metrics_window,
                clamped=False
            ))
        )


@pytest.mark.unit
def test_a_metrics_window_wider_than_the_log_ceiling_is_not_clamped() -> None:
    some_window_start = _an_alert_time()
    window_end_past_only_the_log_ceiling = some_window_start + timedelta(
        minutes=CONFIGURED_WINDOWS.log_max_window_minutes + 1
    )

    # Metrics have their own, wider ceiling - a span the log phase would refuse
    # is ordinary here, which is the whole reason the two resolvers are separate.
    Scenario() \
        .given(
            some_window_start, window_end_past_only_the_log_ceiling
        ) \
        .when(
            lambda: resolve_metrics_window(
                window_start=an_iso_minute(some_window_start),
                window_end=an_iso_minute(window_end_past_only_the_log_ceiling),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_start,
                end=window_end_past_only_the_log_ceiling,
                clamped=False
            ))
        )


@pytest.mark.unit
def test_an_over_span_metrics_window_is_clamped_to_the_metrics_span() -> None:
    some_window_start = _an_alert_time()
    window_end_past_the_metrics_span = some_window_start + timedelta(
        minutes=CONFIGURED_WINDOWS.metrics_window_minutes + 1
    )

    Scenario() \
        .given(
            some_window_start, window_end_past_the_metrics_span
        ) \
        .when(
            lambda: resolve_metrics_window(
                window_start=an_iso_minute(some_window_start),
                window_end=an_iso_minute(window_end_past_the_metrics_span),
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_window_resolved_to(ResolvedWindow(
                start=some_window_start,
                end=some_window_start + timedelta(
                    minutes=CONFIGURED_WINDOWS.metrics_window_minutes
                ),
                clamped=True
            ))
        )


def _the_window_resolved_to(expected: ResolvedWindow) -> Assertion[ResolvedWindow]:
    """The whole window, compared as one value.

    Whole rather than field by field, because the three answers are one
    decision: a resolver that got the start right and the clamp flag wrong has
    not half-passed, it has told the caller something untrue about what it read.
    """
    def assertion(resolved: ResolvedWindow) -> bool:
        if resolved != expected:
            raise AssertionError(f"Expected [{expected}], got [{resolved}].")

        return True

    return assertion


def _the_window_ended_before(bound: datetime) -> Assertion[ResolvedWindow]:
    def assertion(resolved: ResolvedWindow) -> bool:
        if resolved.end is None:
            raise AssertionError(f"Expected an end before [{bound}], got none at all.")

        if resolved.end >= bound:
            raise AssertionError(f"Expected an end before [{bound}], got [{resolved.end}].")

        return True

    return assertion


def _the_window_ended_no_later_than_now() -> Assertion[ResolvedWindow]:
    """That the window does not reach into the future.

    Read at assertion time rather than passed in: `now` advances while the test
    runs, and a bound captured earlier would be the one instant this cannot be
    compared against.
    """
    def assertion(resolved: ResolvedWindow) -> bool:
        now = datetime.now(UTC)

        if resolved.end is None:
            raise AssertionError("Expected an end no later than now, got none at all.")

        if resolved.end > now:
            raise AssertionError(f"Expected an end no later than [{now}], got [{resolved.end}].")

        return True

    return assertion


def _the_window_was_not_clamped() -> Assertion[ResolvedWindow]:
    def assertion(resolved: ResolvedWindow) -> bool:
        if resolved.clamped:
            raise AssertionError("Expected the window not to be reported as clamped.")

        return True

    return assertion


def _a_minute_ago(minutes: int) -> datetime:
    return datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=minutes)


def _an_alert_time() -> datetime:
    """A random minute-aligned instant, far enough back that no window reaches now.

    Anywhere between a day and a month ago - wider than the widest configured
    span, so a test that does not mean to exercise the "now" bound never
    stumbles into it.
    """
    return _a_minute_ago(random.randint(MINUTES_IN_A_DAY, 30 * MINUTES_IN_A_DAY))
