"""What the read tier hands back, once the window has been applied to it.

The window arithmetic is `window.py`'s and is asserted there. What is asserted
here is the other half: that the lines, buckets and changes actually returned
are the ones inside the window that was resolved - including the ones
deliberately left out, since a channel that silently widened its window would
look exactly like one that found more evidence.

The changes channel carries one claim the other two do not: a source that could
not be reached must not arrive looking like one that was read and found nothing.
"No change explains this" is a conclusion something acts on.

The source is a seam in every test. What these functions do with an answer is
the subject; where the answer came from is not.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, NamedTuple
from unittest.mock import create_autospec

import pytest
from argus_core import parse_iso, to_iso
from argus_core.models import ChangeEvent, ChangeKind, MetricBucket
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting, calling
from read_mcp_server.change_source import ChangeSource, ChangeSourceUnavailable
from read_mcp_server.retrieval import (
    get_change_events,
    get_log_lines,
    get_metrics_summary,
)
from read_mcp_server.window import RetrievalSettings

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MINUTES_IN_A_DAY = 24 * 60

SOME_SERVICE = "kukibuki-service"
A_CHANGE_MINUTE = "2026-08-20T11:05:00Z"
A_WHILE = timedelta(hours=1)

# How the read tier says it could not afford the window it was asked for. Spelt
# here as the caller reads it rather than imported: a model is told this in
# prose, and a test sharing the constant would pass on a message that had
# stopped being a sentence.
A_CLAMP_WARNING = "WARN argus-read-mcp: requested window exceeded"

# The windows these retrievals run against, stated rather than read from
# the environment. The clamp tests are arithmetic on the ceiling, and a
# test taking it from the same configuration the code reads would agree
# with itself whatever either said.
CONFIGURED_WINDOWS = RetrievalSettings(
    log_initial_lookback_minutes=30,
    log_initial_lookahead_minutes=10,
    log_max_window_minutes=180,
    metrics_window_minutes=360
)


@pytest.mark.unit
def test_get_log_lines_returns_whatever_fetch_returns() -> None:
    Scenario() \
        .given(
            some_logs := ["INFO line one", "ERROR line two"]
        ) \
        .when(
            lambda: get_log_lines(
                fetch=lambda: some_logs, settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_lines_are(some_logs)
        )


@pytest.mark.unit
def test_get_log_lines_windows_around_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)

    Scenario() \
        .given(
            some_alert_time, some_timeline, some_lines
        ) \
        .when(
            lambda: get_log_lines(
                alert_time=_an_iso_minute(some_alert_time),
                fetch=lambda: some_lines,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_lines_are([
                _a_log_line_at(some_timeline.inside_lookback),
                _a_log_line_at(some_timeline.inside_lookahead)
            ])
        )


@pytest.mark.unit
def test_get_log_lines_explicit_window_overrides_the_alert_time() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)
    a_window_start_around_the_too_late_minute = some_timeline.too_late - timedelta(minutes=1)
    a_window_end_around_the_too_late_minute = some_timeline.too_late + timedelta(minutes=1)

    Scenario() \
        .given(
            some_alert_time,
            a_window_start_around_the_too_late_minute,
            a_window_end_around_the_too_late_minute
        ) \
        .when(
            lambda: get_log_lines(
                alert_time=_an_iso_minute(some_alert_time),
                window_start=_an_iso_minute(a_window_start_around_the_too_late_minute),
                window_end=_an_iso_minute(a_window_end_around_the_too_late_minute),
                fetch=lambda: some_lines,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_lines_are([_a_log_line_at(some_timeline.too_late)])
        )


@pytest.mark.unit
def test_get_log_lines_clamps_an_over_span_window_and_reports_it() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_lines = _some_log_lines_at(some_timeline)
    an_over_span_window_end = some_timeline.too_early + timedelta(
        minutes=CONFIGURED_WINDOWS.log_max_window_minutes + 1
    )

    Scenario() \
        .given(
            some_timeline, an_over_span_window_end
        ) \
        .when(
            lambda: get_log_lines(
                window_start=_an_iso_minute(some_timeline.too_early),
                window_end=_an_iso_minute(an_over_span_window_end),
                fetch=lambda: some_lines,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(all_of(
            _the_clamp_was_reported_first(),
            # The timeline is built to fit inside the ceiling, so no line is
            # lost to the clamp itself - what is asserted is that saying so
            # costs the caller none of the evidence.
            _the_lines_after_the_warning_are(some_lines)
        ))


@pytest.mark.unit
def test_get_log_lines_drops_lines_with_no_timestamp_when_windowed() -> None:
    some_alert_time = _an_alert_time()
    some_timeline = _a_log_timeline_around(some_alert_time)
    some_untimestamped_line = "ERROR target-service: legacy line with no timestamp"
    some_lines = [*_some_log_lines_at(some_timeline), some_untimestamped_line]

    Scenario() \
        .given(
            some_alert_time, some_timeline, some_untimestamped_line
        ) \
        .when(
            lambda: get_log_lines(
                alert_time=_an_iso_minute(some_alert_time),
                fetch=lambda: some_lines,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_lines_are([
                _a_log_line_at(some_timeline.inside_lookback),
                _a_log_line_at(some_timeline.inside_lookahead)
            ])
        )


@pytest.mark.unit
def test_get_metrics_summary_returns_every_bucket_without_a_window() -> None:
    some_alert_time = _an_alert_time()
    some_buckets = [
        _a_bucket(some_alert_time - timedelta(minutes=CONFIGURED_WINDOWS.metrics_window_minutes)),
        _a_bucket(some_alert_time)
    ]

    Scenario() \
        .given(
            some_buckets
        ) \
        .when(
            lambda: get_metrics_summary(
                fetch=lambda: some_buckets, settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_buckets_are(some_buckets)
        )


@pytest.mark.unit
def test_get_metrics_summary_excludes_buckets_outside_the_window() -> None:
    some_alert_time = _an_alert_time()
    a_metrics_window = timedelta(minutes=CONFIGURED_WINDOWS.metrics_window_minutes)
    a_minute_past_the_window = a_metrics_window + timedelta(minutes=1)
    the_bucket_on_the_window_edge = _a_bucket(some_alert_time - a_metrics_window)
    some_buckets = [
        _a_bucket(some_alert_time - a_minute_past_the_window),
        the_bucket_on_the_window_edge,
        _a_bucket(some_alert_time + a_minute_past_the_window)
    ]

    Scenario() \
        .given(
            some_alert_time, the_bucket_on_the_window_edge, some_buckets
        ) \
        .when(
            lambda: get_metrics_summary(
                alert_time=_an_iso_minute(some_alert_time),
                fetch=lambda: some_buckets,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_buckets_are([the_bucket_on_the_window_edge])
        )


@pytest.mark.unit
def test_get_metrics_summary_with_no_active_scenario_returns_no_buckets() -> None:
    Scenario() \
        .given(
            some_alert_time := _an_alert_time()
        ) \
        .when(
            lambda: get_metrics_summary(
                alert_time=_an_iso_minute(some_alert_time),
                fetch=list,
                settings=CONFIGURED_WINDOWS
            )
        ) \
        .then(
            _the_buckets_are([])
        )


@pytest.mark.unit
def test_the_changes_the_source_reports_are_returned() -> None:
    some_revision = "kuki"
    change_source = _a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)

    Scenario() \
        .given(
            calling(the_change_source_reported(
                [_a_deploy_of(some_revision, at=A_CHANGE_MINUTE)]
            ))
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=_a_while_before(A_CHANGE_MINUTE),
                window_end=_a_while_after(A_CHANGE_MINUTE),
                source=change_source
            )
        ) \
        .then(all_of(
            _the_changes_are(some_revision),
            _every_change_is_of_kind(ChangeKind.DEPLOY)
        ))


@pytest.mark.unit
def test_a_window_containing_no_change_is_not_an_error() -> None:
    # Nothing changed is a real answer, and the one the Investigator most needs
    # to be able to trust - it is what makes "no change explains this" sayable.
    change_source = _a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)

    Scenario() \
        .given(
            calling(the_change_source_reported([]))
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=_a_while_before(A_CHANGE_MINUTE),
                window_end=_a_while_after(A_CHANGE_MINUTE),
                source=change_source
            )
        ) \
        .then(
            _no_changes_were_returned()
        )


@pytest.mark.unit
def test_the_service_and_window_asked_about_are_the_ones_passed_on() -> None:
    some_window_start = _a_while_before(A_CHANGE_MINUTE)
    some_window_end = _a_while_after(A_CHANGE_MINUTE)
    change_source = _a_mock_change_source()
    the_change_source_reported = partial(_returning, change_source)
    the_source_was_asked_about = partial(_the_source_was_asked_about, change_source)

    Scenario() \
        .given(
            calling(the_change_source_reported([]))
        ) \
        .when(
            lambda: get_change_events(
                SOME_SERVICE,
                window_start=some_window_start,
                window_end=some_window_end,
                source=change_source
            )
        ) \
        .then(
            the_source_was_asked_about(
                SOME_SERVICE, window_start=some_window_start, window_end=some_window_end
            )
        )


@pytest.mark.unit
def test_an_unreachable_source_surfaces_as_a_failure() -> None:
    # The tool must not turn "could not ask" into "nothing changed" on its way
    # back up - that is the whole reason the source raises rather than
    # returning an empty list.
    change_source = _a_mock_change_source()
    the_change_source_was_unreachable = partial(_raising, change_source)

    Scenario() \
        .given(
            calling(the_change_source_was_unreachable(
                ChangeSourceUnavailable("could not read deploy history")
            ))
        ) \
        .when(
            attempting(
                lambda: get_change_events(
                    SOME_SERVICE,
                    window_start=_a_while_before(A_CHANGE_MINUTE),
                    window_end=_a_while_after(A_CHANGE_MINUTE),
                    source=change_source
                )
            )
        ) \
        .then(
            an_error_was_raised(ChangeSourceUnavailable)
        )


def _the_lines_are(expected: list[str]) -> Assertion[list[str]]:
    """Exactly these lines, in this order.

    Order matters because a reader takes log lines as a sequence of events, and
    exactness because the lines deliberately left out are half of what each of
    these tests is about.
    """
    def assertion(served: list[str]) -> bool:
        if served != expected:
            raise AssertionError(f"Expected lines {expected}, got {served}.")

        return True

    return assertion


def _the_clamp_was_reported_first() -> Assertion[list[str]]:
    """That the caller is told before it is shown anything.

    First rather than anywhere, because a model that asked for three hours,
    silently got one, and found nothing would read the absence of evidence as
    evidence of absence - and a warning after the lines is one it has already
    drawn a conclusion past.
    """
    def assertion(served: list[str]) -> bool:
        if not served:
            raise AssertionError("Expected a clamp warning, got nothing at all.")

        if not served[0].startswith(A_CLAMP_WARNING):
            raise AssertionError(f"Expected a clamp warning first, got [{served[0]}].")

        return True

    return assertion


def _the_lines_after_the_warning_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(served: list[str]) -> bool:
        if served[1:] != expected:
            raise AssertionError(f"Expected lines {expected} after it, got {served[1:]}.")

        return True

    return assertion


def _the_buckets_are(expected: list[MetricBucket]) -> Assertion[list[MetricBucket]]:
    def assertion(served: list[MetricBucket]) -> bool:
        if served != expected:
            raise AssertionError(
                f"Expected the buckets {[bucket.bucket_id for bucket in expected]}, "
                f"got {[bucket.bucket_id for bucket in served]}."
            )

        return True

    return assertion


def _an_alert_time() -> datetime:
    """A random minute-aligned instant, safely in the past.

    Old enough that a window around it cannot be confused with one around now -
    anywhere between a day and a month ago.
    """
    minutes_ago_way_back = random.randint(MINUTES_IN_A_DAY, 30 * MINUTES_IN_A_DAY)
    old_time = datetime.now(UTC) - timedelta(minutes=minutes_ago_way_back)

    return old_time.replace(second=0, microsecond=0)


def _a_timeline_around(alert_time: datetime,
                       lookback_minutes: int,
                       lookahead_minutes: int) -> _Timeline:
    """Four minutes straddling both edges of `[T0 - lookback, T0 + lookahead]`.

    Each offset is random within its band, so a test that passes only because
    of one particular arrangement of minutes will eventually say so.
    How far past an edge a minute may sit is derived, not picked: the whole
    timeline has to fit inside the clamp ceiling, or the clamp test would lose
    lines to the ceiling rather than to the behavior it checks.
    """
    max_minutes_beyond_an_edge = (
        CONFIGURED_WINDOWS.log_max_window_minutes - lookback_minutes - lookahead_minutes
    ) // 2

    def random_minutes_beyond_an_edge() -> int:
        return random.randint(1, max_minutes_beyond_an_edge)

    return _Timeline(
        too_early=alert_time - timedelta(
            minutes=lookback_minutes + random_minutes_beyond_an_edge()),
        inside_lookback=alert_time - timedelta(
            minutes=random.randint(1, lookback_minutes - 1)),
        inside_lookahead=alert_time + timedelta(
            minutes=random.randint(1, lookahead_minutes - 1)),
        too_late=alert_time + timedelta(
            minutes=lookahead_minutes + random_minutes_beyond_an_edge()),
    )


def _a_log_timeline_around(alert_time: datetime) -> _Timeline:
    return _a_timeline_around(
        alert_time,
        lookback_minutes=CONFIGURED_WINDOWS.log_initial_lookback_minutes,
        lookahead_minutes=CONFIGURED_WINDOWS.log_initial_lookahead_minutes,
    )


def _an_iso_minute(minute: datetime) -> str:
    return minute.strftime(TIMESTAMP_FORMAT)


def _a_log_line_at(minute: datetime) -> str:
    return f"{_an_iso_minute(minute)} INFO target-service: some log line"


def _some_log_lines_at(timeline: _Timeline) -> list[str]:
    return [_a_log_line_at(minute) for minute in timeline]


def _a_bucket(minute: datetime, error_rate: float = 0.01) -> MetricBucket:
    return MetricBucket(
        bucket_id=_an_iso_minute(minute),
        error_rate=error_rate,
        p50_ms=40,
        p95_ms=200,
        request_volume=1000,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0,
    )


class _Timeline(NamedTuple):
    """Four minutes, positioned relative to an alert time and the window around it.

    Named rather than indexed: the difference between `inside_lookback` and
    `too_early` is the behavior under test, and `LINES[1]` said nothing about
    which side of which edge it sat on.
    """

    too_early: datetime
    inside_lookback: datetime
    inside_lookahead: datetime
    too_late: datetime


def _a_while_before(moment: str) -> str:
    return to_iso(parse_iso(moment) - A_WHILE)


def _a_while_after(moment: str) -> str:
    return to_iso(parse_iso(moment) + A_WHILE)


def _a_mock_change_source() -> Any:
    """A stand-in for the change channel, spec'd against the port.

    Not against `fetch_deploys`, which takes the reader it asks through:
    what `get_change_events` is handed names a service and a window and
    nothing else.
    """
    return create_autospec(ChangeSource, instance=True)


def _a_deploy_of(revision: str, at: str) -> ChangeEvent:
    some_summary = f"deployed revision {revision}"
    some_actor = "kukibuki"
    some_source = "https://github.com/kukibuki/k8s-configs/apps/target-service/production"

    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=at,
        reference=revision,
        summary=some_summary,
        actor=some_actor,
        source=some_source
    )


def _returning(double: Any, value: Any) -> Callable[[], None]:
    def step() -> None:
        double.return_value = value

    return step


def _raising(double: Any, error: Exception) -> Callable[[], None]:
    def step() -> None:
        double.side_effect = error

    return step


def _the_changes_are(*expected_references: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        found = [change.reference for change in changes]

        if found != list(expected_references):
            raise AssertionError(
                f"Expected changes {list(expected_references)}, got {found}."
            )

        return True

    return assertion


def _no_changes_were_returned() -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        if changes:
            raise AssertionError(f"Expected no changes, got {len(changes)}.")

        return True

    return assertion


def _every_change_is_of_kind(expected_kind: ChangeKind) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        kinds = {change.kind for change in changes}

        if kinds != {expected_kind}:
            raise AssertionError(f"Expected only [{expected_kind}], got {kinds}.")

        return True

    return assertion


def _the_source_was_asked_about(change_source: Any,
                                service: str,
                                window_start: str,
                                window_end: str) -> Assertion[Any]:
    """That the delegation passed on exactly what it was given.

    The tool is a delegation, and what is worth pinning is that it does not
    quietly widen, narrow or re-anchor the window its caller asked for.
    """
    def assertion(_result: Any) -> bool:
        asked_service = change_source.call_args.args[0]
        asked_window = change_source.call_args.kwargs

        if asked_service != service:
            raise AssertionError(
                f"Expected the source to be asked about [{service}], got [{asked_service}]."
            )

        if asked_window["window_start"] != window_start:
            raise AssertionError(
                f"Expected the window to start at [{window_start}], "
                f"got [{asked_window['window_start']}]."
            )

        if asked_window["window_end"] != window_end:
            raise AssertionError(
                f"Expected the window to end at [{window_end}], "
                f"got [{asked_window['window_end']}]."
            )

        return True

    return assertion
