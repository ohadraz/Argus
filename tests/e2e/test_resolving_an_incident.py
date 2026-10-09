"""A person telling Argus the incident is over while Argus is in the middle of it.

The withdrawal's sibling and its opposite at the end. Both stop the walk where
it is; a withdrawal then puts everything back and writes nothing up, where a
resolution leaves everything as it is and writes the incident up - because the
person who reported it over has the world in hand as it stands, and is owed the
account.

Resolved once Argus has changed something, and before the change has been
judged, which is the moment the two endings differ most: there is a flag for a
withdrawal to put back, and the resolution must not. It is also the one moment
a replayed walk can be stopped at deterministically. The double answers in
order and never reads the request, so a stop between two of the investigation's
turns would leave one of its answers queued for the write-up; by the time the
flag has moved, the investigation has had every answer it asks for.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx2
import psycopg
import pytest
from argus_core.events import FixAttempted, StatusChanged
from argus_core.models import IncidentStatus
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_FLAG_TOGGLE,
    REQUEST_TIMEOUT_SECONDS,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import THE_DEMO_FLAG, flags_evaluating_true
from tests.e2e.framework.world import a_scenario_was_seeded

_A_POLL = 0.5

# Who a person pressing the page's button is recorded as, until Argus has users.
THE_DEMO_USER = "demo user"
SOME_NOTE = "kept the flag off and told the checkout team"


@pytest.mark.e2e
def test_an_incident_resolved_mid_walk_keeps_its_flag_off_and_is_written_up() -> None:
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE, less_code_fix=True))
        ) \
        .when(
            _argus_is_resolved_once_it_has_acted_on(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    argus_wrote_a_postmortem(),
                    _the_flag_is_still_off(),
                    _the_account_says_the_demo_user_resolved_it(),
                    _no_fix_was_looked_for()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _argus_is_resolved_once_it_has_acted_on(
    alert: dict[str, object]
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for Argus to turn the flag off, and reports the
    incident over from the page.

    The wait is what makes this a resolution with something to leave in place.
    Until the flag moves there is nothing a wrong unwind could put back, and
    this case would pass against a system that undoes everything on a
    resolution as readily as on a withdrawal.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        resolved = httpx2.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/resolve",
            data={"note": SOME_NOTE},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if resolved.status_code != HttpStatus.OK:
            raise AssertionError(
                f"Resolving incident [{incident_id}] mid-walk answered "
                f"[{resolved.status_code}]: {resolved.text}. Nothing below is "
                f"about an incident a person reported over."
            )

        return response

    return step


def _wait_until_argus_turns_the_flag_off() -> None:
    """Blocks until Mitigation has acted, or says that it never did."""
    deadline = time.monotonic() + MITIGATION_TIMEOUT_SECONDS

    while THE_DEMO_FLAG in flags_evaluating_true():
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Argus never turned [{THE_DEMO_FLAG}] off within "
                f"[{MITIGATION_TIMEOUT_SECONDS}s], so there was never a change for "
                f"a resolution to leave in place."
            )

        time.sleep(_A_POLL)


def _the_flag_is_still_off() -> Assertion[httpx2.Response]:
    """Off, as Argus left it - the change a withdrawal would have put back."""
    def assertion(_response: httpx2.Response) -> bool:
        evaluating = flags_evaluating_true()

        if THE_DEMO_FLAG in evaluating:
            raise AssertionError(
                f"Expected [{THE_DEMO_FLAG}] to stay off after the incident was "
                f"resolved, but the provider evaluates {sorted(evaluating)}."
            )

        return True

    return assertion


def _the_account_says_the_demo_user_resolved_it() -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        reported = [event.reported for event in recorded
                    if isinstance(event, StatusChanged)
                    and event.to_status == IncidentStatus.RESOLVED]

        if (len(reported) != 1 or reported[0] is None
                or reported[0].by != THE_DEMO_USER or reported[0].note != SOME_NOTE):
            raise AssertionError(
                f"Expected one resolution reported by [{THE_DEMO_USER}] saying "
                f"[{SOME_NOTE}], got {reported}."
            )

        return True

    return assertion


def _no_fix_was_looked_for() -> Assertion[httpx2.Response]:
    """Code-Fix never ran: whatever the incident needed, the person did."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        attempts = [event for event in recorded if isinstance(event, FixAttempted)]

        if attempts:
            raise AssertionError(
                f"Expected no fix looked for after the incident was resolved, got "
                f"{len(attempts)} attempt(s)."
            )

        return True

    return assertion
