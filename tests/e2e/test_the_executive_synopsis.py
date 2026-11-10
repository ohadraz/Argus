"""Who is told what the response cost, over an incident somebody was paged for.

The executive synopsis states the response's cost, which is pay: what the
people who answered the page earn for the minutes they spent on it. So it goes
to the people configured to receive it and to nobody else - here a member and a
channel, the two shapes the setting takes - and the figure it carries reaches
nowhere else the responders it prices can read: not the war room, not the
incident's thread, not an HTML page of Argus's. The synopsis's own PDF, which
its Slack message links to, is the one route that serves it, by choice.

The figure is the stored postmortem's, said as the synopsis says money. That
the synopsis carries it is asserted too, so its absence everywhere else is an
absence of something that exists rather than of something nobody priced.

The pages are read as HTML. The postmortem's PDF is printed from the same
words as its page, so a figure the page does not say is one the PDF does not
print.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx2
import psycopg
import pytest
from argus_core import get_settings, utc_now
from argus_core.models import said_as_money
from argus_incidents.repository import postmortems
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE_PRICED,
    REQUEST_TIMEOUT_SECONDS,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.chat import posted_to_slack
from tests.e2e.framework.oncall import the_on_call_platform_holds
from tests.e2e.framework.pay_bands import THE_CHEAPER_TITLE, THE_DEARER_TITLE
from tests.e2e.framework.world import a_scenario_was_seeded

A_MINUTE = timedelta(minutes=1)

# Every page of Argus's that shows an incident, or a list of them.
THE_PAGES_OF = ("/", "/now", "/history", "/history/list",
                "/incidents/{incident_id}", "/incidents/{incident_id}/walk",
                "/incidents/{incident_id}/postmortem")


@pytest.mark.e2e
def test_the_response_cost_reaches_the_synopsis_readers_and_nobody_else() -> None:
    dont_care_alert_name = "HighErrorRate"
    dont_care_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=dont_care_alert_name,
                                            severity=dont_care_severity)

    dont_care_on_call_incident = "PSOMEINCIDENT"
    some_responder = "PSOMEONE"
    some_other_responder = "PSOMEONEELSE"
    # Each acknowledges the page before it is closed, so both spent minutes on it.
    some_wait_to_acknowledge = 1 * A_MINUTE
    some_other_wait_to_acknowledge = 2 * A_MINUTE
    some_wait_to_resolve = 10 * A_MINUTE

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle",
                                          as_recorded_in=RECORDED_FLAG_TOGGLE_PRICED)),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE_PRICED)),
            calling(the_on_call_platform_holds(
                dont_care_on_call_incident,
                paged_for=some_alert,
                paged_at=utc_now(),
                resolved_after=some_wait_to_resolve,
                acknowledged_after={some_responder: some_wait_to_acknowledge,
                                    some_other_responder: some_other_wait_to_acknowledge},
                titles={some_responder: THE_DEARER_TITLE,
                        some_other_responder: THE_CHEAPER_TITLE}
            )),
            said_before := len(posted_to_slack())
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually` on the posts alone: the relay sends the synopsis after
            # the walk stores it, and once both ids have it nothing else about
            # the incident is still to come.
            all_of(
                eventually(_each_id_was_sent_the_synopsis(said_before),
                           timeout=WALK_TIMEOUT_SECONDS),
                _the_synopsis_carries_the_response_cost(said_before),
                _no_other_message_carries_the_response_cost(said_before),
                _no_page_carries_the_response_cost()
            )
        )


def _the_ids() -> list[str]:
    """Who the synopsis is sent to, as the stack was configured."""
    return [one.strip() for one in get_settings().executive_synopsis_slack_to.split(",")]


def _said_since(already: int) -> list[dict[str, Any]]:
    return posted_to_slack()[already:]


def _the_response_cost_of(response: httpx2.Response) -> str:
    """The stored postmortem's response cost, said as money is said
    everywhere Argus says it."""
    incident_id = incident_id_from(response)

    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None or postmortem.responder_cost_estimate is None:
        raise AssertionError(
            f"Expected incident [{incident_id}]'s postmortem to price the response, "
            f"it is [{postmortem}].")

    return said_as_money(postmortem.responder_cost_estimate,
                         postmortem.responder_cost_currency)


def _each_id_was_sent_the_synopsis(already: int) -> Assertion[httpx2.Response]:
    """One message to each configured id - a member's direct message and a
    channel's post - and no more than one."""
    def assertion(_: httpx2.Response) -> bool:
        said = _said_since(already)
        counted = {one: sum(1 for message in said if message["channel"] == one)
                   for one in _the_ids()}
        if any(count != 1 for count in counted.values()):
            raise AssertionError(
                f"Expected one synopsis to each of {_the_ids()}, got {counted}.")

        return True

    return assertion


def _the_synopsis_carries_the_response_cost(already: int) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        cost = _the_response_cost_of(response)
        without = [message["channel"] for message in _said_since(already)
                   if message["channel"] in _the_ids() and cost not in message["text"]]
        if without:
            raise AssertionError(
                f"Expected the synopsis to say the response cost [{cost}], the one "
                f"sent to {without} does not.")

        return True

    return assertion


def _no_other_message_carries_the_response_cost(already: int) -> Assertion[httpx2.Response]:
    """Nothing in the war room, the incident's thread or any other channel
    says the figure."""
    def assertion(response: httpx2.Response) -> bool:
        cost = _the_response_cost_of(response)
        leaked = [(message["channel"], message["text"]) for message in _said_since(already)
                  if message["channel"] not in _the_ids() and cost in message["text"]]
        if leaked:
            raise AssertionError(
                f"Expected the response cost [{cost}] said only to {_the_ids()}, "
                f"it was said in {leaked}.")

        return True

    return assertion


def _no_page_carries_the_response_cost() -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        cost = _the_response_cost_of(response)
        incident_id = incident_id_from(response)
        leaked = []

        for page in THE_PAGES_OF:
            path = page.format(incident_id=incident_id)
            shown = httpx2.get(f"{ARGUS_WEB_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)
            shown.raise_for_status()

            if cost in shown.text:
                leaked.append(path)

        if leaked:
            raise AssertionError(
                f"Expected no page to show the response cost [{cost}], {leaked} do.")

        return True

    return assertion
