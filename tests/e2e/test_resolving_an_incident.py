"""A person telling Argus the incident is over while Argus is in the middle of it.

The withdrawal's sibling and its opposite at the end. Both stop the walk where
it is; a withdrawal then puts everything back and writes nothing up, where a
resolution leaves everything as it is and writes the incident up - because the
person who reported it over has the world in hand as it stands, and is owed the
account.

Three places the report comes from, and one ending: Argus's own incident page,
the on-call platform where the person was paged, and the incident's own Slack
thread. From the platform, the incident is matched by the key the alert came in
with, never by Argus's id, which the platform has never heard of. From the
thread, the person's words are only read: Argus offers the resolution back to
them, and it is their press that ends the incident.

From the page and the platform, resolved once Argus has changed something,
and before the change has been judged, which is the moment the two endings
differ most: there is a flag for a withdrawal to put back, and the resolution
must not. It is also the one moment a replayed walk can be stopped at
deterministically. The double answers in order and never reads the request, so
a stop between two of the investigation's turns would leave one of its answers
queued for the write-up; by the time the flag has moved, the investigation has
had every answer it asks for.

From the thread, in an order rather than at a moment. The person writes while
the walk's model is held, so their words are on the incident before Argus has
investigated anything; Argus then waits after its first step for their answer,
and their press is the next thing that happens to it. Nothing here races the
walk, so nothing here can lose to it. That a resolution leaves Argus's changes
in place is the page's case, and the same for every channel.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import psycopg
import pytest
from argus_core import utc_now
from argus_core.events import FixAttempted, StatusChanged
from argus_core.models import IncidentStatus, Report, ReportChannel
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
    the_held_model_answers_from,
    the_model_answers_from,
    the_model_is_held,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.chat import (
    RECORDED_INTENT_RESOLVE,
    THE_WORDS_CLASSIFIED_AS_RESOLVED,
    a_person_writes,
    the_chat_platform_knows,
    the_intent_agent_answers_from,
    the_offer_made_in,
    the_offer_now_names,
    the_person_presses,
    the_thread_of,
)
from tests.e2e.framework.flags import THE_DEMO_FLAG, flags_evaluating_true
from tests.e2e.framework.oncall import (
    a_resolution_by,
    the_on_call_platform_delivers,
    the_on_call_platform_holds,
)
from tests.e2e.framework.world import a_scenario_was_seeded

_A_POLL = 0.5

A_MINUTE = timedelta(minutes=1)

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
            _argus_is_resolved_once_it_has_acted_on(
                some_alert, _from_the_incident_page(SOME_NOTE))
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    argus_wrote_a_postmortem(),
                    _the_flag_is_still_off(),
                    _the_account_says_it_was_resolved(
                        Report(by=THE_DEMO_USER,
                               channel=ReportChannel.ARGUS_UI,
                               note=SOME_NOTE)),
                    _no_fix_was_looked_for()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_an_incident_resolved_in_pagerduty_keeps_its_flag_off_and_is_written_up() -> None:
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")
    some_on_call_incident = "PSOMEINCIDENT"
    some_person = "Some Person"
    some_person_id = "PSOMEONE"
    some_resolution_note = "kept the flag off and paged the checkout team"

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE, less_code_fix=True)),
            calling(the_on_call_platform_holds(
                some_on_call_incident,
                paged_for=some_alert,
                paged_at=utc_now(),
                resolved_after=10 * A_MINUTE,
                acknowledged_after={some_person_id: 1 * A_MINUTE},
                resolution_note=some_resolution_note
            ))
        ) \
        .when(
            _argus_is_resolved_once_it_has_acted_on(
                some_alert,
                _from_the_on_call_platform(
                    some_on_call_incident, some_person, some_person_id))
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    argus_wrote_a_postmortem(),
                    _the_flag_is_still_off(),
                    _the_account_says_it_was_resolved(
                        Report(by=some_person,
                               channel=ReportChannel.PAGERDUTY,
                               note=some_resolution_note)),
                    _no_fix_was_looked_for()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_an_incident_resolved_from_its_slack_thread_is_written_up_and_nothing_more() -> None:
    # The person writes that it is over, Argus offers the resolution back to
    # them, and their press is what ends it - credited to them, with their
    # words as the note. Argus waits for that answer rather than carrying on,
    # so no fix is looked for. The offer is then rewritten to say how it ended,
    # so the thread does not go on asking a question that has been answered.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")
    some_person = "Some Person"
    some_person_id = "U0SOMEONE"
    offered: dict[str, dict[str, Any]] = {}

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_is_held()),
            calling(the_intent_agent_answers_from(RECORDED_INTENT_RESOLVE)),
            calling(the_chat_platform_knows(some_person_id, some_person))
        ) \
        .when(
            _argus_is_resolved_from_the_slack_thread_before_it_investigates(
                some_alert, some_person_id, THE_WORDS_CLASSIFIED_AS_RESOLVED, offered)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    argus_wrote_a_postmortem(),
                    _the_account_says_it_was_resolved(
                        Report(by=some_person,
                               channel=ReportChannel.SLACK,
                               note=THE_WORDS_CLASSIFIED_AS_RESOLVED)),
                    _no_fix_was_looked_for(),
                    the_offer_now_names(offered, some_person)
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _argus_is_resolved_once_it_has_acted_on(
    alert: dict[str, object],
    resolve: Callable[[str], httpx2.Response]
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for Argus to turn the flag off, and reports the
    incident over through `resolve`.

    The wait is what makes this a resolution with something to leave in place.
    Until the flag moves there is nothing a wrong unwind could put back, and
    this case would pass against a system that undoes everything on a
    resolution as readily as on a withdrawal.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        resolved = resolve(incident_id)

        if resolved.status_code not in (HttpStatus.OK, HttpStatus.ACCEPTED):
            raise AssertionError(
                f"Resolving incident [{incident_id}] mid-walk answered "
                f"[{resolved.status_code}]: {resolved.text}. Nothing below is "
                f"about an incident a person reported over."
            )

        return response

    return step


def _from_the_incident_page(note: str) -> Callable[[str], httpx2.Response]:
    """A person pressing the incident page's button, with a note."""
    def resolve(incident_id: str) -> httpx2.Response:
        return httpx2.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/resolve",
            data={"note": note},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

    return resolve


def _from_the_on_call_platform(on_call_incident: str,
                               person: str,
                               person_id: str) -> Callable[[str], httpx2.Response]:
    """A person resolving the platform's incident, delivered as PagerDuty would.

    Argus's own id is ignored: the platform names its own incident, and finding
    Argus's from it is the thing under test.
    """
    def resolve(_incident_id: str) -> httpx2.Response:
        return the_on_call_platform_delivers(
            a_resolution_by(person, person_id, on_call_incident))

    return resolve


def _argus_is_resolved_from_the_slack_thread_before_it_investigates(
    alert: dict[str, object],
    person_id: str,
    words: str,
    offered: dict[str, dict[str, Any]]
) -> Callable[[], httpx2.Response]:
    """Fires the alert with the walk's model held, writes in the incident's
    thread, lets the walk go, and presses what Argus offers.

    Ordered by the hold rather than timed: the person's words are on the
    incident before the walk has taken a step, so the walk waits after its
    first one - and the press, whenever it comes, is the next thing that
    happens to it.

    The offer is kept in `offered`, so that what became of it can be asserted
    once the incident has ended.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        thread = the_thread_of(incident_id_from(response))
        written = a_person_writes(person_id, words, in_thread=thread)

        the_held_model_answers_from(RECORDED_FLAG_TOGGLE, less_code_fix=True)()

        offered["offer"] = the_offer_made_in(thread)
        pressed = the_person_presses(person_id, offered["offer"], about=written)

        if pressed.status_code not in (HttpStatus.OK, HttpStatus.ACCEPTED):
            raise AssertionError(
                f"The press on the offer answered [{pressed.status_code}]: {pressed.text}. "
                f"Nothing below is about an incident a person reported over."
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


def _the_account_says_it_was_resolved(expected: Report) -> Assertion[httpx2.Response]:
    """One resolution on the account: who reported it, where, and what they wrote."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        reported = [event.reported for event in recorded
                    if isinstance(event, StatusChanged)
                    and event.to_status == IncidentStatus.RESOLVED]

        if reported != [expected]:
            raise AssertionError(
                f"Expected one resolution reported as {expected}, got {reported}."
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
