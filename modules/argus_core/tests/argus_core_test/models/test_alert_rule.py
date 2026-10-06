"""What a rule's standing may say about how the rule reads its service.

The three durations are how long a recovery takes to show in the rule, and a
rule still firing is judged at their sum past the change. A negative one brings
that moment forward, to before the rule could have seen a recovery - and a
mitigation that worked would be refuted for it.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_core.models import AlertRuleStanding
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from pydantic import ValidationError

DURATIONS = ["range_seconds", "interval_seconds", "keep_firing_for_seconds"]


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


def a_standing(**overrides: int) -> dict[str, Any]:
    return {
        "rule": "some-rule",
        "is_normal": True,
        "evaluated_at": datetime(2026, 10, 6, 10, 20, tzinfo=UTC),
        "range_seconds": 300,
        "interval_seconds": 60,
        "keep_firing_for_seconds": 120,
        **overrides
    }


def _it_holds(duration: str, expected: int) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        held = getattr(standing, duration)

        if held != expected:
            raise AssertionError(f"Expected [{duration}] to hold [{expected}], got [{held}].")

        return True

    return assertion
