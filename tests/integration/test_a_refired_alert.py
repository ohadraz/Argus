"""An alert Grafana sends again, and the incident it belongs to.

Grafana repeats a notification while its alert is still firing - a reminder,
every four hours by default - and an alert that stops firing and starts again
is a new firing, sent under the same group key. Both arrive at Argus looking
like the first. The two questions here are about telling them apart where it
matters: which incident a notification belongs to, and which incident a person
resolving the page meant.

A firing is an alert's fingerprint and the moment it started, which Grafana
stamps on every alert of every notification, reminder or not. A reminder of a
firing an incident holds is that incident, however it ended - unless Argus said
it mitigated it, since an alarm still going contradicts that, and the
contradiction is a new incident. A new firing is a new incident too, under a
group key an older one may already hold; a person resolving its page resolves
the incident whose life that page overlaps, never an older one that happens to
share the key.

Across modules because the defect lives between them: the parser says what a
notification names, intake decides what it joins, the schema decides what two
incidents may both hold, and the on-call door decides which of them a page
reaches. The on-call platform is stood in through the app's own seam - what
PagerDuty says is decided in the adapter's suite - and everything else is real.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from http import HTTPStatus as HttpStatus
from typing import Any, Final
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_core import connect_from_env, utc_now
from argus_core.models import NOTIFICATION_KEY, IncidentStatus, ReportChannel
from argus_incidents.repository import incidents, references
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app, oncall_platform_of
from fastapi.testclient import TestClient
from oncall_source import ReportedIncident
from oncall_source.platform import OnCallPlatform, ResolvedByAPerson

ALERTS_WEBHOOK: Final = "/webhooks/alerts"
ONCALL_WEBHOOK: Final = "/webhooks/oncall"

# Grafana's words for an alert's state, said on the envelope and on each alert.
FIRING: Final = "firing"
RESOLVED: Final = "resolved"

SOME_SERVICE = "io-shop"
SOME_OTHER_SERVICE = "fx-rates"
SOME_RULE = "some-rule"
SOME_ALERT_NAME = "HighErrorRate"
# Grafana's default grouping is by folder and alert name, so one group spans
# every service its rule watches.
SOME_GROUP_KEY = f'{{}}/{{alertname="{SOME_ALERT_NAME}"}}'
SOME_FINGERPRINT = "a1b2c3d4e5f60718"
SOME_OTHER_FINGERPRINT = "0f1e2d3c4b5a6978"
# When a firing started, as Grafana spells it. Fixed rather than now, because
# nothing here reads a metric.
SOME_START = "2026-10-14T15:59:00Z"
A_LATER_START = "2026-10-14T17:20:00Z"
SOME_PAGE = "PSOMEPAGE"
SOME_PERSON = "Some Person"
DONT_CARE_BODY = b"{}"


@pytest.fixture(autouse=True)
def no_platform_left_behind() -> Iterator[None]:
    """The app's seam put back after each case that stood a platform in."""
    yield
    app.dependency_overrides.pop(oncall_platform_of, None)


@pytest.mark.integration
@pytest.mark.parametrize("ending", [
    IncidentStatus.DISPROVEN,
    IncidentStatus.WITHDRAWN,
    IncidentStatus.ESCALATED,
    IncidentStatus.RECOMMENDED,
    IncidentStatus.RESOLVED
])
def test_a_reminder_of_a_firing_joins_the_incident_it_opened_however_it_ended(
    ending: IncidentStatus
) -> None:
    # None of these endings says the alarm stopped: escalated and recommended
    # left the work with a person, disproven called the alarm the rule's, and
    # withdrawn and resolved are a person's word. The alarm still going is
    # what each of them predicts, and a second walk would pay again for an
    # answer the incident already has.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(ending, _the_incident_opened_by(client, the_firing))
            ) \
            .when(lambda: client.post(ALERTS_WEBHOOK, json=the_firing)) \
            .then(all_of(
                _it_was_answered_with(first),
                _incidents_were_opened_for(SOME_SERVICE, count=1)
            ))


@pytest.mark.integration
def test_a_reminder_of_a_firing_argus_said_it_mitigated_opens_a_new_incident() -> None:
    # Argus said the symptom stopped, and the alarm says it has not. That is a
    # claim the world contradicted, and what it leaves is an incident to walk.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.MITIGATED,
                                   _the_incident_opened_by(client, the_firing))
            ) \
            .when(lambda: client.post(ALERTS_WEBHOOK, json=the_firing)) \
            .then(all_of(
                _it_was_answered_with_a_new_incident(besides=first),
                _incidents_were_opened_for(SOME_SERVICE, count=2)
            ))


@pytest.mark.integration
def test_a_new_firing_of_an_alert_whose_incident_ended_opens_a_new_incident() -> None:
    # The alert stopped and started again: the same group and fingerprint, a
    # new start. That is a second incident, whatever became of the first.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))
    its_resolution = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START, status=RESOLVED))
    the_next_firing = _a_notification(_an_alert(SOME_FINGERPRINT, A_LATER_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.ESCALATED,
                                   _the_incident_opened_by(client, the_firing)),
                _grafana_said(client, its_resolution)
            ) \
            .when(lambda: client.post(ALERTS_WEBHOOK, json=the_next_firing)) \
            .then(all_of(
                _it_was_answered_with_a_new_incident(besides=first),
                _incidents_were_opened_for(SOME_SERVICE, count=2)
            ))


@pytest.mark.integration
def test_a_reminder_listing_a_newer_alert_first_joins_the_incident_it_opened() -> None:
    # A group's alerts come in whatever order Grafana lists them, and a
    # reminder can put an alert that started since ahead of the one that
    # opened the incident. The firing still going is the incident's all the
    # same.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))
    a_reminder = _a_notification(_an_alert(SOME_OTHER_FINGERPRINT, A_LATER_START),
                                 _an_alert(SOME_FINGERPRINT, SOME_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.ESCALATED,
                                   _the_incident_opened_by(client, the_firing))
            ) \
            .when(lambda: client.post(ALERTS_WEBHOOK, json=a_reminder)) \
            .then(all_of(
                _it_was_answered_with(first),
                _incidents_were_opened_for(SOME_SERVICE, count=1)
            ))


@pytest.mark.integration
def test_a_reminder_led_by_another_services_alert_opens_that_services_incident() -> None:
    # One group spans every service its rule watches, so the incident holds
    # firings that are not its own. A notification joins an incident about
    # the service it is about, and this one is about the other service.
    the_firing = _a_notification(
        _an_alert(SOME_FINGERPRINT, SOME_START),
        _an_alert(SOME_OTHER_FINGERPRINT, SOME_START, service=SOME_OTHER_SERVICE)
    )
    a_reminder = _a_notification(
        _an_alert(SOME_OTHER_FINGERPRINT, SOME_START, service=SOME_OTHER_SERVICE),
        _an_alert(SOME_FINGERPRINT, SOME_START)
    )

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.ESCALATED,
                                   _the_incident_opened_by(client, the_firing))
            ) \
            .when(lambda: client.post(ALERTS_WEBHOOK, json=a_reminder)) \
            .then(all_of(
                _it_was_answered_with_a_new_incident(besides=first),
                _incidents_were_opened_for(SOME_OTHER_SERVICE, count=1)
            ))


@pytest.mark.integration
def test_a_person_resolving_a_new_firings_page_resolves_the_new_incident() -> None:
    # PagerDuty opened a page for each firing, both under the group's key, and
    # closed the first when its alert stopped. The person resolved the second.
    # The first incident was escalated, which a resolution is accepted from -
    # so a page reaching the wrong incident would visibly move it. The page's
    # key is read off the first incident because every firing of the group
    # pages under the same one, and the first holds it however the second
    # fares.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))
    its_resolution = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START, status=RESOLVED))
    the_next_firing = _a_notification(_an_alert(SOME_FINGERPRINT, A_LATER_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.ESCALATED,
                                   _the_incident_opened_by(client, the_firing)),
                _grafana_said(client, its_resolution),
                second := _the_incident_opened_by(client, the_next_firing),
                _the_platform_is(_a_page_resolved_by_a_person(
                    SOME_PAGE,
                    keys=_the_keys_held_by(first),
                    opened_at=_the_start_of(second)
                ))
            ) \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                _the_incident_is(second, IncidentStatus.RESOLVED),
                _the_incident_is(first, IncidentStatus.ESCALATED)
            ))


@pytest.mark.integration
def test_a_person_resolving_a_page_two_incidents_share_resolves_both() -> None:
    # Argus said it mitigated the first and the alarm went on, so the second
    # is the same firing - and PagerDuty kept one page open across both. The
    # person resolving it is ending both.
    the_firing = _a_notification(_an_alert(SOME_FINGERPRINT, SOME_START))

    with TestClient(app) as client:
        Scenario() \
            .given(
                first := _ended_as(IncidentStatus.MITIGATED,
                                   _the_incident_opened_by(client, the_firing)),
                second := _the_incident_opened_by(client, the_firing),
                _the_platform_is(_a_page_resolved_by_a_person(
                    SOME_PAGE,
                    keys=_the_keys_held_by(first),
                    opened_at=_the_start_of(first)
                ))
            ) \
            .when(lambda: client.post(ONCALL_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                _the_incident_is(first, IncidentStatus.RESOLVED),
                _the_incident_is(second, IncidentStatus.RESOLVED)
            ))


def _a_notification(*alerts: dict[str, Any]) -> dict[str, Any]:
    """One notification of `SOME_GROUP_KEY`'s group, carrying these alerts
    nested the way Grafana nests them - firing while any of them is."""
    return {
        "receiver": "argus-webhook",
        "status": FIRING if any(alert["status"] == FIRING for alert in alerts) else RESOLVED,
        "alerts": list(alerts),
        "groupLabels": {"alertname": SOME_ALERT_NAME},
        "externalURL": "http://grafana.local",
        "version": "1",
        "groupKey": SOME_GROUP_KEY
    }


def _an_alert(fingerprint: str,
              starts_at: str,
              service: str = SOME_SERVICE,
              status: str = FIRING) -> dict[str, Any]:
    """One alert of the group: `SOME_RULE` firing for `service`, the firing
    named by its fingerprint and the moment it started."""
    return {
        "status": status,
        "labels": {"alertname": SOME_ALERT_NAME, "service": service},
        "annotations": {"summary": f"Error rate above threshold on {service}"},
        "startsAt": starts_at,
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": f"http://grafana.local/alerting/grafana/{SOME_RULE}/view",
        "fingerprint": fingerprint
    }


def _grafana_said(client: TestClient, notification: dict[str, Any]) -> httpx2.Response:
    """One notification delivered, whatever it was answered with."""
    return client.post(ALERTS_WEBHOOK, json=notification)


def _the_incident_opened_by(client: TestClient, notification: dict[str, Any]) -> str:
    """The incident one notification was answered with."""
    answered = _grafana_said(client, notification)
    incident_id = (answered.json().get("incident_id")
                   if answered.status_code == HttpStatus.ACCEPTED else None)

    if not incident_id:
        raise AssertionError(
            f"Expected the notification to be answered with an incident, and it was "
            f"answered [{answered.status_code}] {answered.text}. Nothing below is about "
            f"an incident."
        )

    return str(incident_id)


def _ended_as(status: IncidentStatus, incident_id: str) -> str:
    """The incident, ended as `status` through the door that ending comes
    through: a person's through theirs, Argus's through the walk's.

    The two are guarded differently, and an ending written through the wrong
    one is a row no running system could leave.
    """
    with connect_from_env() as conn:
        match status:
            case IncidentStatus.RESOLVED:
                ended = incidents.resolve(conn, incident_id)
            case IncidentStatus.WITHDRAWN:
                ended = incidents.withdraw(conn, incident_id)
            case _:
                ended = incidents.transition(conn, incident_id, status)
                conn.commit()

    if not ended:
        raise AssertionError(
            f"Expected incident [{incident_id}] to end as [{status}], and it did not "
            f"move. Nothing below is about an incident that ended."
        )

    return incident_id


def _the_keys_held_by(incident_id: str) -> list[str]:
    """The keys the monitor paged under for this incident, as Argus holds them."""
    with connect_from_env() as conn:
        return references.get_values_for(conn, incident_id, NOTIFICATION_KEY)


def _the_start_of(incident_id: str) -> datetime:
    with connect_from_env() as conn:
        incident = incidents.get(conn, incident_id)

    if incident is None:
        raise AssertionError(f"Expected incident [{incident_id}] to exist, and found none.")

    return incident.created_at


def _a_page_resolved_by_a_person(page: str, keys: list[str], opened_at: datetime) -> Any:
    """The platform, saying a person resolved `page`: opened at `opened_at`,
    carrying `keys`, and resolved now."""
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.channel = ReportChannel.PAGERDUTY
    platform.parse_delivery.return_value = ResolvedByAPerson(platform_incident=page,
                                                             by=SOME_PERSON)
    platform.keys_of.return_value = keys
    platform.resolution_note.return_value = None
    platform.reported_incident.return_value = ReportedIncident(began_at=opened_at,
                                                               ended_at=utc_now(),
                                                               acknowledgements=[])

    return platform


def _the_platform_is(platform: Any) -> Any:
    """FastAPI's own seam for standing something in; put back by
    `no_platform_left_behind`."""
    app.dependency_overrides[oncall_platform_of] = lambda: platform

    return platform


def _it_was_answered_with(incident_id: str) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        answered = response.json().get("incident_id")

        if answered != incident_id:
            raise AssertionError(
                f"Expected the notification to be answered with incident "
                f"[{incident_id}], got [{answered}]."
            )

        return True

    return assertion


def _it_was_answered_with_a_new_incident(besides: str) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        answered = response.json().get("incident_id")

        if answered is None or answered == besides:
            raise AssertionError(
                f"Expected the notification to open an incident other than "
                f"[{besides}], got [{answered}]."
            )

        return True

    return assertion


def _incidents_were_opened_for(service: str, count: int) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            opened = [incident for incident in incidents.get_recent(conn)
                      if incident.alert_payload.get("service") == service]

        if len(opened) != count:
            raise AssertionError(
                f"Expected [{count}] incident(s) for [{service}], got [{len(opened)}]."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        found = incident.status if incident is not None else None

        if found != status:
            raise AssertionError(
                f"Expected incident [{incident_id}] to be [{status}], got [{found}]."
            )

        return True

    return assertion
