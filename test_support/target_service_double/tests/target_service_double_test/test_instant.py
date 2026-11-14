"""When a replayed scenario is seeded: its recording's own instant, moved forward
by whole minutes to the first one the replay has not yet passed.

Whole minutes, because the shop draws each minute's figures from the minute's
own name, and a world moved by anything else would be drawn from minutes the
recording never had. The anchor's seconds, to the microsecond, because the shop
dates an outage's first minute by them: a seed a second off is a different share
of that minute broken, and a different count of failures in it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_testkit import Assertion, Scenario
from target_service_double.instant import the_seed_instant

SOME_ANCHOR = datetime(2026, 9, 28, 22, 11, 43, 502554, tzinfo=UTC)


@pytest.mark.unit
def test_a_replay_is_seeded_at_the_anchors_own_second_in_the_first_minute_still_ahead() -> None:
    some_moment_before_that_second = datetime(2026, 10, 14, 3, 50, 10, tzinfo=UTC)

    Scenario() \
        .given(SOME_ANCHOR) \
        .when(lambda: the_seed_instant(SOME_ANCHOR, now=some_moment_before_that_second)) \
        .then(_the_instant_is(datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)))


@pytest.mark.unit
def test_a_replay_already_past_the_anchors_second_is_seeded_in_the_next_minute() -> None:
    # Never before now: the shop seeds at the instant it is asked to, and an
    # instant already behind the stack's clock is one nobody can wait for.
    some_moment_after_that_second = datetime(2026, 10, 14, 3, 50, 50, tzinfo=UTC)

    Scenario() \
        .given(SOME_ANCHOR) \
        .when(lambda: the_seed_instant(SOME_ANCHOR, now=some_moment_after_that_second)) \
        .then(_the_instant_is(datetime(2026, 10, 14, 3, 51, 43, 502554, tzinfo=UTC)))


@pytest.mark.unit
def test_a_replay_arriving_exactly_at_the_anchors_second_is_seeded_then() -> None:
    exactly_that_second = datetime(2026, 10, 14, 3, 50, 43, 502554, tzinfo=UTC)

    Scenario() \
        .given(SOME_ANCHOR) \
        .when(lambda: the_seed_instant(SOME_ANCHOR, now=exactly_that_second)) \
        .then(_the_instant_is(exactly_that_second))


@pytest.mark.unit
def test_an_anchor_later_than_now_is_brought_back_to_the_first_minute_still_ahead() -> None:
    # A stack whose clock reads earlier than the day the set was recorded on -
    # a machine with its clock set back, or a set recorded on a faster clock.
    # The rule is the same either way: the first matching instant not behind now.
    some_moment_days_before_the_anchor = datetime(2026, 9, 20, 8, 0, 0, tzinfo=UTC)

    Scenario() \
        .given(SOME_ANCHOR) \
        .when(lambda: the_seed_instant(SOME_ANCHOR, now=some_moment_days_before_the_anchor)) \
        .then(_the_instant_is(datetime(2026, 9, 20, 8, 0, 43, 502554, tzinfo=UTC)))


def _the_instant_is(expected: datetime) -> Assertion[datetime]:
    def assertion(seeded_at: datetime) -> bool:
        if seeded_at != expected:
            raise AssertionError(
                f"Expected the replay to be seeded at [{expected.isoformat()}], "
                f"got [{seeded_at.isoformat()}]."
            )

        return True

    return assertion
