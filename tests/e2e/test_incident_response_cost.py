from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from http import HTTPStatus as HttpStatus

import httpx
import psycopg
import pytest
from agent_postmortem.document import (
    PAY_BAND_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from argus_core.config import get_settings
from argus_core.models.postmortem import Postmortem
from argus_incidents.repository import postmortems
from argus_testkit import Assertion, Scenario, all_of, calling
from argus_testkit.assertions import eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

"""What the response cost, over an incident somebody was actually paged for.

The minutes have their own file. This is the second half of the same figure:
the pay band of each responder's title, read from an HR system Argus reaches
over the network like any other provider. Every layer between the two is a
place the cost can quietly become absent - a credential nobody set, a title the
bands do not carry, an endpoint answering a shape the adapter cannot read - and
each of those is a legitimate answer on its own, which is why only a run of the
whole stack tells them apart from a figure that was priced.

The figure is bounded rather than named. How many minutes the response took
depends on how fast Argus happened to walk the incident, so an exact
expectation would be an assertion about wall-clock. What is not free to vary is
the rate: whatever the minutes were, they were spent by people on one of two
known bands, so the cost has to sit between those minutes at the cheaper band
and the same minutes at the dearer one. A figure outside that is a rate nobody
published.
"""

# The bands the Target Service's HR endpoint publishes for the two titles it
# pages.
# MIRRORED FROM THE DEMO APP - NOT ARBITRARY VALUES!!!
# A fixture that moves fails here saying the cost left the band it was priced
# from, which is the failure worth having.
THE_CHEAPEST_MIDPOINT = Decimal(175_000)
THE_DEAREST_MIDPOINT = Decimal(220_000)

MINUTES_AN_HOUR = Decimal(60)


@pytest.mark.e2e
def test_an_incident_somebody_was_paged_for_prices_the_minutes_they_spent() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_a_feature_flag_was_toggled_on()),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually`, for the reason every postmortem assertion here is:
            # the webhook answers as soon as the incident exists, and a worker
            # walks it and writes the document minutes afterwards.
            eventually(
                all_of(
                    _the_postmortem_prices_the_response(),
                    _the_figure_carries_the_band_it_came_from(),
                    _the_arithmetic_was_disclosed()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_postmortem_prices_the_response() -> Assertion[httpx.Response]:
    """A cost, over the minutes the same document reports.

    Bounded by the two bands rather than named exactly: the minutes depend on
    how long the walk took, and asserting a figure would be asserting Argus's
    own speed. The bounds still fail every wrong rate - a year divided by the
    wrong divisor, a salary read where a band was meant, one responder priced
    and the other dropped.
    """
    def assertion(response: httpx.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        incident_id = incident_id_from(response)

        if postmortem.responder_cost_estimate is None:
            raise AssertionError(
                f"Postmortem for [{incident_id}] prices no response, over an "
                f"incident two people with published bands were paged for. It "
                f"says: {postmortem.assumptions}.")

        if postmortem.engineer_minutes is None:
            raise AssertionError(
                f"Postmortem for [{incident_id}] carries a response cost of "
                f"[{postmortem.responder_cost_estimate}] and no minutes to have "
                f"priced, so the two figures describe different responses.")

        cheapest, dearest = _what_those_minutes_can_cost(postmortem.engineer_minutes)

        if not cheapest <= postmortem.responder_cost_estimate <= dearest:
            raise AssertionError(
                f"Postmortem for [{incident_id}] puts the response cost at "
                f"[{postmortem.responder_cost_estimate}] for "
                f"[{postmortem.engineer_minutes}] minutes, outside the "
                f"[{cheapest}] to [{dearest}] those minutes can come to at the "
                f"bands the HR source publishes.")

        return True

    return assertion


def _the_figure_carries_the_band_it_came_from() -> Assertion[httpx.Response]:
    """The range beside the figure, and the currency it is in.

    A midpoint published alone claims a precision a band does not have, so a
    document carrying the headline and neither edge has lost the thing that
    makes it honest. The minimum below the maximum, because two bands collapsed
    to one point would satisfy every other assertion here.
    """
    def assertion(response: httpx.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        incident_id = incident_id_from(response)
        low, high = postmortem.responder_cost_minimum, postmortem.responder_cost_maximum

        if low is None or high is None:
            raise AssertionError(
                f"Postmortem for [{incident_id}] publishes a response cost of "
                f"[{postmortem.responder_cost_estimate}] with no range around "
                f"it: [{low}] to [{high}].")

        if not low < high:
            raise AssertionError(
                f"Postmortem for [{incident_id}] reports a range from [{low}] "
                f"to [{high}], which is not a band.")

        if not postmortem.responder_cost_currency:
            raise AssertionError(
                f"Postmortem for [{incident_id}] prices the response at "
                f"[{postmortem.responder_cost_estimate}] and names no currency, "
                f"so the figure is a number rather than money.")

        return True

    return assertion


def _the_arithmetic_was_disclosed() -> Assertion[httpx.Response]:
    """Both things the figure rests on that nobody measured.

    The working year is the divisor that turns an annual band into a per-minute
    rate, and the band is a range this document collapsed to a point. A reader
    who cannot see either is being asked to take the cost on trust, and this is
    the one assertion here that could not pass without the HR source in the
    path.
    """
    def assertion(response: httpx.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        incident_id = incident_id_from(response)
        stated = postmortem.assumptions or []

        for label in (WORKING_YEAR_ASSUMPTION_LABEL, PAY_BAND_ASSUMPTION_LABEL):
            if not any(label in assumption for assumption in stated):
                raise AssertionError(
                    f"Postmortem for [{incident_id}] discloses no [{label}] "
                    f"behind its response cost. It says: {stated}.")

        return True

    return assertion


def _what_those_minutes_can_cost(minutes: int) -> tuple[Decimal, Decimal]:
    """The least and the most the figure can honestly be.

    Every responder is on one of the two bands, so the whole response cannot
    cost less than all of it at the cheaper midpoint nor more than all of it at
    the dearer one. The working year comes from the same settings the agent
    priced with, rather than from a number repeated here: the divisor is
    configuration, and a test hardcoding it would disagree with a deployment
    that changed it.
    """
    a_year = Decimal(str(get_settings().working_hours_a_year)) * MINUTES_AN_HOUR

    return (THE_CHEAPEST_MIDPOINT * minutes / a_year,
            THE_DEAREST_MIDPOINT * minutes / a_year)


def _the_postmortem_for(response: httpx.Response) -> Postmortem:
    incident_id = incident_id_from(response)

    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None:
        raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

    return postmortem


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    """The scenario that breaks the shop and gets somebody paged for it.

    Its own copy rather than another test module's: a test reaching into a
    neighbour's `_name` is the same violation here as anywhere else in this
    repo.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
