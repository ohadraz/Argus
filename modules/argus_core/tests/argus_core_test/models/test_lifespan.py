"""When something was going on, and whether two such things were going on at once.

An Argus incident and the on-call platform's incident are opened by the same
alert and never told about each other, and a key the monitor paged under is
shared by every firing of its group. What ties a page to the incident it is
about is time: the two were going on together. Two doors ask it - a person's
resolution arriving from the platform, and the postmortem reading who
responded - and they must give the same answer, which is why the rule is one
value's rather than each door's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import Lifespan
from argus_testkit import Assertion, Scenario

SOME_MOMENT = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
A_MINUTE = timedelta(minutes=1)


@pytest.mark.unit
@pytest.mark.parametrize(("one", "other"), [
    (Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT + 5 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE)),
    (Lifespan(began_at=SOME_MOMENT + 5 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE))
], ids=["earlier-first", "later-first"])
def test_two_lives_that_share_a_moment_overlap(one: Lifespan, other: Lifespan) -> None:
    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(True))


@pytest.mark.unit
@pytest.mark.parametrize(("one", "other"), [
    (Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT + 11 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE)),
    (Lifespan(began_at=SOME_MOMENT + 11 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE))
], ids=["earlier-first", "later-first"])
def test_a_life_that_ended_before_another_began_does_not_overlap_it(one: Lifespan,
                                                                    other: Lifespan) -> None:
    # The page of an alert's earlier firing closed before this firing began: it
    # is about another incident, however many keys the two share.
    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(False))


@pytest.mark.unit
@pytest.mark.parametrize(("one", "other"), [
    (Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT + 10 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE)),
    (Lifespan(began_at=SOME_MOMENT + 10 * A_MINUTE, ended_at=SOME_MOMENT + 20 * A_MINUTE),
     Lifespan(began_at=SOME_MOMENT, ended_at=SOME_MOMENT + 10 * A_MINUTE))
], ids=["earlier-first", "later-first"])
def test_lives_that_touch_overlap(one: Lifespan, other: Lifespan) -> None:
    # One ended in the instant the other began. Two clocks cannot place those
    # apart, and an incident and its page are stamped by two clocks.
    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(True))


@pytest.mark.unit
@pytest.mark.parametrize(("one", "other"), [
    (Lifespan(began_at=SOME_MOMENT, ended_at=None),
     Lifespan(began_at=SOME_MOMENT - 5 * A_MINUTE, ended_at=SOME_MOMENT + A_MINUTE)),
    (Lifespan(began_at=SOME_MOMENT - 5 * A_MINUTE, ended_at=SOME_MOMENT + A_MINUTE),
     Lifespan(began_at=SOME_MOMENT, ended_at=None))
], ids=["going-first", "ended-first"])
def test_a_life_still_going_overlaps_one_that_ended_after_it_began(one: Lifespan,
                                                                   other: Lifespan) -> None:
    # An incident Argus is still on has no end yet, and is going on now.
    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(True))


@pytest.mark.unit
@pytest.mark.parametrize(("one", "other"), [
    (Lifespan(began_at=SOME_MOMENT, ended_at=None),
     Lifespan(began_at=SOME_MOMENT - 10 * A_MINUTE, ended_at=SOME_MOMENT - A_MINUTE)),
    (Lifespan(began_at=SOME_MOMENT - 10 * A_MINUTE, ended_at=SOME_MOMENT - A_MINUTE),
     Lifespan(began_at=SOME_MOMENT, ended_at=None))
], ids=["going-first", "ended-first"])
def test_a_life_still_going_does_not_overlap_one_that_ended_before_it_began(
        one: Lifespan, other: Lifespan) -> None:
    # Having no end is not having no start: what was over before it began was
    # not going on at the same time.
    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(False))


@pytest.mark.unit
def test_two_lives_still_going_overlap() -> None:
    one = Lifespan(began_at=SOME_MOMENT, ended_at=None)
    other = Lifespan(began_at=SOME_MOMENT + 10 * A_MINUTE, ended_at=None)

    Scenario() \
        .when(lambda: one.overlaps(other)) \
        .then(_the_answer_is(True))


def _the_answer_is(expected: bool) -> Assertion[bool]:
    def assertion(overlaps: bool) -> bool:
        if overlaps is not expected:
            raise AssertionError(
                f"Expected the two lives to {'overlap' if expected else 'not overlap'}, "
                f"and overlaps answered [{overlaps}]."
            )

        return True

    return assertion
