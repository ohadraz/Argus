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

from __future__ import annotations

from decimal import Decimal

import httpx
import psycopg
import pytest
from agent_postmortem import EXCHANGE_RATE_ASSUMPTION_LABEL
from argus_incidents.repository import postmortems
from argus_testkit import Assertion, Scenario, all_of, calling
from argus_testkit.assertions import eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded

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
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually` on the row alone: the webhook answers as soon as the
            # incident exists and a worker walks it afterwards, so the document
            # arrives minutes later. What it says is settled the moment it does
            # - it is written once and never updated - so the figures are
            # asserted once rather than retried against a deadline.
            all_of(
                eventually(argus_wrote_a_postmortem(),
                           timeout=WALK_TIMEOUT_SECONDS),
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
