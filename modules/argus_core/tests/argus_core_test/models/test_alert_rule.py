"""What a rule's standing may say about how the rule reads its service.

Three of the durations are how long a recovery takes to show in the rule, and a
rule still firing is judged at their sum past the change. A negative one brings
that moment forward, to before the rule could have seen a recovery - and a
mitigation that worked would be refuted for it. The fourth, how long the rule's
condition holds before it fires, is part of the time from an onset to its alert,
and a negative one would make a late alert read as an early one.

And what unit the rule's series is in, which is what lets a level be said as a
level rather than as a bare number - and which is unknown unless something says
it, rather than guessed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_core.models import AlertRuleStanding
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from pydantic import ValidationError

DURATIONS = ["range_seconds", "interval_seconds", "keep_firing_for_seconds", "pending_seconds"]


@pytest.mark.unit
@pytest.mark.parametrize("duration", DURATIONS)
def test_a_negative_duration_is_refused(duration: str) -> None:
    Scenario() \
        .given(negative := {duration: -1}) \
        .when(
            attempting(lambda: AlertRuleStanding.model_validate(a_standing(**negative)))
        ) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
@pytest.mark.parametrize("duration", DURATIONS)
def test_a_duration_of_nothing_is_accepted(duration: str) -> None:
    # A rule that is a check rather than a query over a range looks back over
    # nothing, and one may keep firing for no time at all once its condition
    # clears.
    Scenario() \
        .given(nothing := {duration: 0}) \
        .when(lambda: AlertRuleStanding.model_validate(a_standing(**nothing))) \
        .then(_it_holds(duration, 0))


@pytest.mark.unit
def test_a_standing_that_names_no_unit_leaves_the_unit_unknown() -> None:
    # Unknown rather than defaulted: a level said in a unit nobody named is a
    # level said wrongly the first time the series is not in that unit.
    Scenario() \
        .when(lambda: AlertRuleStanding.model_validate(a_standing())) \
        .then(_its_unit_is(None))


@pytest.mark.unit
def test_the_unit_a_standing_names_is_the_unit_it_holds() -> None:
    Scenario() \
        .given(in_milliseconds := {"series_unit": "ms"}) \
        .when(lambda: AlertRuleStanding.model_validate(a_standing(**in_milliseconds))) \
        .then(_its_unit_is("ms"))


def a_standing(**overrides: Any) -> dict[str, Any]:
    return {
        "rule": "some-rule",
        "is_normal": True,
        "evaluated_at": datetime(2026, 10, 6, 10, 20, tzinfo=UTC),
        "range_seconds": 300,
        "interval_seconds": 60,
        "keep_firing_for_seconds": 120,
        "pending_seconds": 300,
        **overrides
    }


def _its_unit_is(expected: str | None) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.series_unit != expected:
            raise AssertionError(
                f"Expected the series' unit to be [{expected}], got [{standing.series_unit}]."
            )

        return True

    return assertion


def _it_holds(duration: str, expected: int) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        held = getattr(standing, duration)

        if held != expected:
            raise AssertionError(f"Expected [{duration}] to hold [{expected}], got [{held}].")

        return True

    return assertion
