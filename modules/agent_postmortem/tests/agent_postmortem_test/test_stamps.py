"""When a log line was logged, read from the minute it opens with - and how far
the lines read reach into a stretch the metrics did not cover.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_postmortem.stamps import stamped, the_last_minute_logged_inside
from argus_testkit import Scenario, the_answer_was

SOME_ERROR = "ERROR io-shop: account page request failed - ZeroDivisionError at spend_summary.py:47"
SOME_RATE = "WARN io-shop: account page error rate at {}% over the last minute"


@pytest.mark.unit
def test_the_last_minute_logged_inside_a_stretch_is_its_latest_stamp() -> None:
    # How far the logs reach into a stretch, which naming what reached in does
    # not say: told only which, a model wrote that the logs ran up to the alert
    # and that nothing was known after the onset. The latest stamp rather than
    # the last line, since lines are not read in the order they were logged;
    # and the minute, not the second, since a line is stamped with the whole
    # of its minute.
    some_lines = [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                  f"2026-10-11T23:43:30Z {SOME_ERROR}",
                  f"2026-10-11T23:41:00Z {SOME_RATE.format('24.00')}"]

    Scenario() \
        .given(
            the_stretch_began := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: the_last_minute_logged_inside(some_lines, the_stretch_began)
        ) \
        .then(
            the_answer_was(datetime(2026, 10, 11, 23, 43, tzinfo=UTC))
        )


@pytest.mark.unit
def test_a_stretch_no_line_was_logged_inside_has_no_last_minute() -> None:
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {SOME_ERROR}", SOME_ERROR]
        ) \
        .when(
            lambda: the_last_minute_logged_inside(some_lines,
                                                  datetime(2026, 10, 11, 23, 40, tzinfo=UTC))
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_line_logged_at_or_after_where_a_stretch_ended_is_not_inside_it() -> None:
    # A stretch the metrics did not cover ends where they resumed, and a line
    # logged once they had is the service measured again, not seen through its
    # logs alone. By the instant its stamp names: the minute they resumed in
    # holds lines from either side of it.
    some_lines = [f"2026-10-11T23:41:00Z {SOME_RATE.format('1.50')}",
                  f"2026-10-11T23:43:00Z {SOME_ERROR}",
                  f"2026-10-11T23:43:30Z {SOME_RATE.format('24.00')}",
                  f"2026-10-11T23:45:00Z {SOME_ERROR}"]

    Scenario() \
        .given(
            the_stretch_ended := datetime(2026, 10, 11, 23, 43, 20, tzinfo=UTC)
        ) \
        .when(
            lambda: the_last_minute_logged_inside(some_lines,
                                                  datetime(2026, 10, 11, 23, 40, tzinfo=UTC),
                                                  the_stretch_ended)
        ) \
        .then(
            the_answer_was(datetime(2026, 10, 11, 23, 43, tzinfo=UTC))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("stamp", "logged_at"), [
    ("2026-10-11T23:39Z", datetime(2026, 10, 11, 23, 39, tzinfo=UTC)),
    ("2026-10-11T23:39:30Z", datetime(2026, 10, 11, 23, 39, 30, tzinfo=UTC)),
    ("2026-10-11T23:39:30.125Z", datetime(2026, 10, 11, 23, 39, 30, 125000, tzinfo=UTC)),
    ("2026-10-11T23:39:30+00:00", datetime(2026, 10, 11, 23, 39, 30, tzinfo=UTC)),
    ("2026-10-12T01:39:30.125+02:00", datetime(2026, 10, 11, 23, 39, 30, 125000, tzinfo=UTC)),
    ("2026-10-11T23:39:30", datetime(2026, 10, 11, 23, 39, 30, tzinfo=UTC))
], ids=["a-minute", "a-second", "a-fraction-of-a-second", "an-offset",
        "a-fraction-and-an-offset", "no-zone"])
def test_a_stamp_is_read_as_the_instant_it_names(stamp: str, logged_at: datetime) -> None:
    # As the read tier reads it. A service logging to the millisecond, or with
    # an offset rather than a Z, had lines with no stamp at all: no span, no
    # minutes, nothing to say they were logged after Argus acted. A stamp with
    # no zone is UTC's, as the read tier takes it.
    Scenario() \
        .given(stamp) \
        .when(
            lambda: stamped(f"{stamp} {SOME_ERROR}")
        ) \
        .then(
            the_answer_was((logged_at, SOME_ERROR))
        )


@pytest.mark.unit
def test_a_date_with_no_time_is_no_stamp() -> None:
    # A log line opens with when it was logged, which a date alone does not say.
    Scenario() \
        .given(
            some_line := f"2026-10-11 {SOME_ERROR}"
        ) \
        .when(
            lambda: stamped(some_line)
        ) \
        .then(
            the_answer_was((None, some_line))
        )
