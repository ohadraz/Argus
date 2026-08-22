from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from argus_core.config import get_settings
from argus_core.timestamps import parse_iso

settings = get_settings()


class ResolvedWindow(NamedTuple):
    """The time window a retrieval call actually ran against.

    `start`/`end` are both `None` only when the caller supplied no alert time
    and no window at all, which means "no window" - the pass-through behavior
    `agent_investigator` still relies on. `clamped` records that the caller
    asked for a wider span than configuration allows and got a narrower one,
    so the tool can say so instead of silently returning less than was asked
    for.
    """

    start: datetime | None
    end: datetime | None
    clamped: bool


def _resolve_window(alert_time: str | None,
                    window_start: str | None,
                    window_end: str | None,
                    lookback_minutes: int,
                    lookahead_minutes: int,
                    max_span_minutes: int) -> ResolvedWindow:
    """Works out which time window a retrieval call should run against.

    An explicit `window_start`/`window_end` wins; otherwise an `alert_time`
    `T0` derives `[T0 - lookback, min(now, T0 + lookahead)]`. The upper bound
    tracks "now" so that a live incident's newly elapsed minutes come into
    range without the caller asking for them (spec §16); stopping there is not
    a clamp, since no minute that existed to be read was withheld. An explicit
    window is clamped to `max_span_minutes`, anchored at the start - the
    earliest minutes are the ones that explain onset, so a too-wide request
    loses its tail rather than its head. An open-ended explicit window is
    unbounded, hence also clamped.
    """
    max_span = timedelta(minutes=max_span_minutes)
    start = parse_iso(window_start) if window_start is not None else None
    end = parse_iso(window_end) if window_end is not None else None

    if start is not None and end is not None:
        if end - start > max_span:
            return ResolvedWindow(start=start, end=start + max_span, clamped=True)

        return ResolvedWindow(start=start, end=end, clamped=False)

    # A half-open explicit window is unbounded, so it too gets clamped - back
    # from the end when that is the bound the caller named.
    if start is not None:
        return ResolvedWindow(start=start, end=start + max_span, clamped=True)

    if end is not None:
        return ResolvedWindow(start=end - max_span, end=end, clamped=True)

    if alert_time is None:
        return ResolvedWindow(start=None, end=None, clamped=False)

    anchor = parse_iso(alert_time)

    return ResolvedWindow(
        start=anchor - timedelta(minutes=lookback_minutes),
        end=min(datetime.now(UTC), anchor + timedelta(minutes=lookahead_minutes)),
        clamped=False,
    )


def resolve_log_window(alert_time: str | None = None,
                       window_start: str | None = None,
                       window_end: str | None = None) -> ResolvedWindow:
    """The window a `get_log_lines` call runs against.

    Log lines are the expensive phase, so the configured lookback/lookahead
    are deliberately narrow and apply to the *first* iteration only - a
    reasoning caller that has seen the metrics summary supplies its own window
    thereafter, bounded by `log_max_window_minutes` (spec §16, §9).
    """
    return _resolve_window(
        alert_time,
        window_start,
        window_end,
        lookback_minutes=settings.log_initial_lookback_minutes,
        lookahead_minutes=settings.log_initial_lookahead_minutes,
        max_span_minutes=settings.log_max_window_minutes,
    )


def resolve_metrics_window(alert_time: str | None = None,
                           window_start: str | None = None,
                           window_end: str | None = None) -> ResolvedWindow:
    """The window a `get_metrics_summary` call runs against.

    One fixed, wide span rather than something that narrows and widens:
    metrics are what locate the onset, so a narrow metrics window can hide the
    very thing the loop is looking for, and at four numbers a minute there is
    no reason to be stingy (spec §16). Its ceiling is its own span, not the
    log ceiling - a span the log phase would refuse is ordinary here.
    """
    return _resolve_window(
        alert_time,
        window_start,
        window_end,
        lookback_minutes=settings.metrics_window_minutes,
        lookahead_minutes=settings.metrics_window_minutes,
        max_span_minutes=settings.metrics_window_minutes,
    )
