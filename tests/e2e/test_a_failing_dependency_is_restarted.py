"""The incident Argus was not paged about.

Every other scenario here is answered by acting on the service that alerted. A
flag the shop serves behind, a deployment of the shop, the shop's own heap -
whatever the cause, the thing Argus reaches for is the thing the alert named. A
dependency's failure is the first case where that is the wrong answer and
looks like the right one: the shop is the thing failing its users, restarting
it is the obvious first response, and it provably changes nothing.

Three things this case pins that no other one can.

**A cause the metrics cannot name.** Every quantile climbs together and the
error rate never moves, which is the signature of a slow deployment - and the
deploy history is empty, so the reading the shape suggests is refuted by the
one channel that could confirm it. What names the cause is a single WARN line
in the shop's own log, saying which host the time went to.

**A service register read as evidence.** Whether `io-pricing` may be touched
exists in no metric and in no log. It is recorded by a person, in a document
nobody reads until an incident, and Argus reads it as a retrieval channel
rather than being configured with the answer - which is what lets the same walk
tell this apart from an upstream provider's outage, where the register says the
thing on the other end is somebody else's.

**A mitigation aimed somewhere the alert never named.** The restart is
addressed to `io-pricing`, and what admits it is two separate questions: its
kind is in the declared set (§13), and its address is a dependency the register
marks as this organisation's own. The action recorded against the incident is
therefore worth reading for its *subject*, not only its kind - a restart of the
shop would satisfy every other assertion here and end nothing.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run
proves the path exists - the register reaching the model as a tool, the address
surviving into the hypothesis, the second gate letting it past, and the write
tier restarting and confirming the right application. Under `nox -s e2e` a real
model reads a real dependency failure and decides for itself whose it is.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import pytest
from argus_core.events import ActionTaken
from argus_core.models import RESTART_SERVICE, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_PRICING_SERVICE_DEGRADED,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import the_incidents_events

A_LATENCY_ALERT = "HighLatency"

# The service the shop calls while it renders the account page, and the one the
# register says this organisation owns. Not a constant in the framework,
# because no other case knows it exists - which is the point of the scenario.
THE_FAILING_DEPENDENCY = "io-pricing"


@pytest.mark.e2e
def test_a_failing_dependency_is_restarted_rather_than_the_service_that_alerted() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_pricing_service_was_left_slow()),
            calling(the_model_answers_from(RECORDED_PRICING_SERVICE_DEGRADED))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_action_taken_was_a_restart_of(THE_FAILING_DEPENDENCY),
                    _the_service_that_alerted_was_not_restarted(),
                    _the_latency_climbed_and_then_came_back_down(),
                    _the_error_rate_never_moved()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_action_taken_was_a_restart_of(service: str) -> Assertion[httpx.Response]:
    """Read from the incident's own account, and read for its subject.

    Every other restart in this suite is addressed to the service the alert
    named, so asserting the kind alone has always been enough. Here it is not:
    a walk that restarted the shop would record a restart, satisfy a check on
    the kind, and have done nothing whatever about the incident.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing "
                f"was ever put to the question."
            )

        restarts = [
            event for event in taken
            if event.action_type == RESTART_SERVICE and event.subject == service
        ]

        if not restarts:
            raise AssertionError(
                f"Expected a restart of [{service}], and what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]}."
            )

        if restarts[-1].a_dependency_of != THE_SERVICE_NAME:
            raise AssertionError(
                f"Expected the account to say [{service}] was restarted as a "
                f"dependency of [{THE_SERVICE_NAME}], and it said "
                f"[{restarts[-1].a_dependency_of}] - so a reader is left with a "
                f"service that appears nowhere else in the incident and no "
                f"reason Argus was allowed to touch it."
            )

        return True

    return assertion


def _the_service_that_alerted_was_not_restarted() -> Assertion[httpx.Response]:
    """The wrong answer, asserted against directly.

    Restarting the shop is the obvious first response to the shop being slow,
    it is admitted by every gate, and the fixture proves it changes nothing.
    An incident that tried it and then found the dependency would still reach
    `mitigated` - and would have taken production down for a moment to learn
    what the register could have told it.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        restarts_of_the_shop = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
            and event.action_type == RESTART_SERVICE
            and event.subject == THE_SERVICE_NAME
        ]

        if restarts_of_the_shop:
            raise AssertionError(
                f"Incident [{incident_id}] restarted [{THE_SERVICE_NAME}], "
                f"which this scenario is built so that nothing comes of - the "
                f"walk reached the right answer having first done something to "
                f"production for no reason."
            )

        return True

    return assertion


def _the_latency_climbed_and_then_came_back_down() -> Assertion[httpx.Response]:
    """The evidence the restart was of the thing that was actually slow.

    Asserted on the shop's own window, because the shop is what the users
    experience and what the alert was about. A restart of the dependency that
    left the shop still waiting would be a mitigation that reached the wrong
    service and reported success.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = _the_shops_window()
        slowest = max(minute["p95_ms"] for minute in window)
        now = window[-1]["p95_ms"]

        if now * 2 > slowest:
            raise AssertionError(
                f"Expected the wait to be over, and the window's slowest minute "
                f"was [{slowest}]ms against [{now}]ms now."
            )

        return True

    return assertion


def _the_error_rate_never_moved() -> Assertion[httpx.Response]:
    """What makes this incident hard, asserted so it stays hard.

    Nothing fails: the dependency answers every call, slowly. A fixture that
    let the error rate rise would hand the investigation the signal every other
    scenario here turns on, and this case would stop being about latency with
    no failures at all.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        worst = max(minute["error_rate"] for minute in _the_shops_window())

        # Nothing fails here, but "nothing" is not zero: the shop's ordinary
        # minute loses a percent or three, and the incident this case is not
        # about loses a third of every page. The bound separates those two
        # rather than pinning the noise.
        if worst > 0.10:
            raise AssertionError(
                f"Expected the shop to keep answering, and its worst minute "
                f"failed [{worst:.1%}] of requests - which is a different "
                f"incident from the one this case is about."
            )

        return True

    return assertion


def _the_shops_window() -> list[dict[str, Any]]:
    """The Target Service's own metrics, insisting there are some."""
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/metrics", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    window: list[dict[str, Any]] = response.json()

    if not window:
        raise AssertionError(
            "The shop is reporting no minutes at all, so nothing here can say "
            "what its latency or its error rate did."
        )

    return window


def _the_pricing_service_was_left_slow() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "pricing-service-degraded"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
