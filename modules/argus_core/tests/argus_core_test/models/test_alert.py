"""What an alert has to carry, and what it is allowed to leave out.

The first thing Argus is ever told about an incident, and the only one it does
not produce itself: a monitoring system sends it. So the two questions worth
asking of the model are the two a sender can get wrong - what may be omitted,
and what may not.
"""
from __future__ import annotations

import pytest
from argus_core.models.alert import Alert
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from pydantic import ValidationError


@pytest.mark.unit
def test_an_alert_that_said_no_more_than_it_had_to_assumes_nothing() -> None:
    # `severity` and `summary` are the sender's to add, and most senders do not.
    # Defaulted to anything else, a walk would report a severity nobody stated.
    Scenario() \
        .given(
            some_service := "checkout",
            some_alert_name := "HighErrorRate"
        ) \
        .when(
            lambda: Alert(service=some_service, alert_name=some_alert_name)
        ) \
        .then(
            _nothing_was_assumed_about("severity", "summary")
        )


@pytest.mark.unit
def test_an_alert_naming_no_service_is_refused() -> None:
    # The service is what every retrieval is about. An alert without one would
    # be an incident nothing could be read for.
    Scenario() \
        .given(
            some_alert_name := "HighErrorRate"
        ) \
        .when(
            attempting(
                lambda: Alert.model_validate({"alert_name": some_alert_name})
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


def _nothing_was_assumed_about(*fields: str) -> Assertion[Alert]:
    """That each named field came back `None` rather than filled in.

    Named together rather than checked one at a time, because the claim is
    about the model's posture towards what it was not told - and a field that
    quietly grew a default would pass a test written about its neighbour.
    """
    def assertion(alert: Alert) -> bool:
        assumed = {field: getattr(alert, field) for field in fields}
        filled = {field: value for field, value in assumed.items() if value is not None}

        if filled:
            raise AssertionError(f"Expected nothing assumed, got {filled}.")

        return True

    return assertion
