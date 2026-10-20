"""When a log line was logged, read from the minute it opens with - and how far
the lines read reach into a stretch the metrics did not cover.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_postmortem.stamps import the_last_minute_logged_inside
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
