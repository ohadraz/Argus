from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from http import HTTPStatus as HttpStatus

import httpx
import psycopg
import pytest
from agent_postmortem.document import EXCHANGE_RATE_ASSUMPTION_LABEL
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import postmortems

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

"""What the incident cost, over a shop that was actually taking money.

The estimate is the one figure in a postmortem that rests on something outside
Argus entirely - a payment provider - and every layer between the two is a
place it can quietly become absent: a credential nobody set, a window the
provider reports nothing for, a currency the document cannot state. Each of
those is a legitimate answer on its own, which is exactly why only a run of the
whole stack can tell them apart from a figure that was measured.

So this asserts a number rather than a field being populated: the shop's own
endpoint derives its charges from the very minutes `/metrics` reports, so an
incident that broke the shop must cost more than nothing, and an estimate of
zero over a window with charges in it means the money never reached the
arithmetic.

It says nothing about how large the loss is. Two of the four terms come from
the model's judgment and the incident's own duration, and a suite asserting a
range would be asserting how fast Argus happened to run.
"""

SOME_SECOND_CURRENCY = "eur"


@pytest.mark.e2e
def test_an_incident_over_a_trading_window_costs_a_measured_amount() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_feature_flag_was_toggled_on(),
            the_model_answers_from(RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # No `eventually`: the webhook answers only once the graph has run
            # to the end, so the postmortem row is already written and final by
            # the time this reads it. Retrying it would be waiting on a value
            # that cannot change - eight and a half minutes of it, as the first
            # run of this test spent proving.
            all_of(
                _the_postmortem_estimates_a_loss(),
                _the_conversion_was_disclosed()
            )
        )


def _the_postmortem_estimates_a_loss() -> Assertion[httpx.Response]:
    """The document carries a figure the payment provider is behind.

    The assumptions are reported on failure and not asserted on: when the
    estimate is absent, the document has already written down why, and a
    failure that reprints that reason is the difference between "the estimate
    is missing" and knowing which of the four ways it went missing.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            postmortem = postmortems.get_by_incident(conn, incident_id)

        if postmortem is None:
            raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

        if postmortem.customer_loss_estimate is None:
            raise AssertionError(
                f"Postmortem for [{incident_id}] estimates no loss, over a window "
                f"in which the shop was taking money. It says: "
                f"{postmortem.assumptions}.")

        if postmortem.customer_loss_estimate <= Decimal(0):
            raise AssertionError(
                f"Postmortem for [{incident_id}] puts the loss at "
                f"[{postmortem.customer_loss_estimate}], so nothing the shop "
                f"took reached the arithmetic.")

        return True

    return assertion


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    """The scenario that both breaks the shop and gives it something to lose.

    Its own copy rather than the one in `test_scenario_investigation.py`: that
    one is private to its file, and a test reaching into another test module's
    `_name` is the same violation anywhere else in this repo.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def _the_conversion_was_disclosed() -> Assertion[httpx.Response]:
    """The figure came through a rate, and the document says which.

    The shop takes a minority of its orders in euros, so an estimate that
    disclosed no conversion was built from the dollar orders alone - the
    arithmetic would look right and the money would be short. This is the one
    assertion here that could not pass without the rate source in the path.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            postmortem = postmortems.get_by_incident(conn, incident_id)

        if postmortem is None:
            raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

        disclosed = [stated for stated in postmortem.assumptions or []
                     if EXCHANGE_RATE_ASSUMPTION_LABEL in stated
                     and SOME_SECOND_CURRENCY in stated]

        if not disclosed:
            raise AssertionError(
                f"Postmortem for [{incident_id}] discloses no rate for "
                f"[{SOME_SECOND_CURRENCY}], so its estimate rests on the "
                f"home-currency orders alone. It says: {postmortem.assumptions}.")

        return True

    return assertion
