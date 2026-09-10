from __future__ import annotations

import pytest
from argus_core.events import AlertAcknowledged, IncidentEvent, nobody
from argus_core.models.alert import Alert
from argus_incidents.publishing import acknowledge_alert
from argus_testkit import Assertion, Scenario, all_of, calling

"""The first line of an incident's story.

The moment Argus has the alert and has looked at nothing yet. An account that
opens on the Investigator already working starts mid-sentence: the reader never
sees the thing that set it off.

The account is never part of the work, which is the other half of what these
cover - acknowledging with nobody listening has to be as ordinary as
acknowledging with a subscriber, because the default everywhere else in this
system is that nobody is.
"""

SOME_INCIDENT_ID = "some-incident"
DONT_CARE_ALERT = Alert(service="io-shop", alert_name="HighErrorRate")


@pytest.mark.unit
def test_receiving_the_alert_is_the_first_line_of_the_incidents_story() -> None:
    published: list[IncidentEvent] = []
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    Scenario() \
        .given(
            calling(lambda: acknowledge_alert(SOME_INCIDENT_ID,
                                              some_alert,
                                              published.append))
        ) \
        .when(lambda: published) \
        .then(all_of(_exactly_one_event_was_published(),
                     _the_acknowledgement_is_about(SOME_INCIDENT_ID, some_alert)))


@pytest.mark.unit
def test_an_alert_nobody_is_listening_for_is_still_received() -> None:
    Scenario() \
        .given(DONT_CARE_ALERT) \
        .when(lambda: acknowledge_alert(SOME_INCIDENT_ID, DONT_CARE_ALERT, nobody)) \
        .then(_nothing_went_wrong())


def _exactly_one_event_was_published() -> Assertion[list[IncidentEvent]]:
    def assertion(published: list[IncidentEvent]) -> bool:
        if len(published) != 1:
            raise AssertionError(
                f"expected one event, got {len(published)}: {published}"
            )

        return True

    return assertion


def _the_acknowledgement_is_about(incident_id: str,
                                  alert: Alert) -> Assertion[list[IncidentEvent]]:
    def assertion(published: list[IncidentEvent]) -> bool:
        acknowledged = published[0]
        if not isinstance(acknowledged, AlertAcknowledged):
            raise AssertionError(
                f"expected an AlertAcknowledged, got {type(acknowledged).__name__}"
            )

        if (acknowledged.incident_id, acknowledged.alert) != (incident_id, alert):
            raise AssertionError(
                f"expected an acknowledgement of {alert} on [{incident_id}], got "
                f"{acknowledged.alert} on [{acknowledged.incident_id}]"
            )

        return True

    return assertion


def _nothing_went_wrong() -> Assertion[None]:
    """There is nothing to observe, which is the point: with no subscriber the
    call has to be as ordinary as with one."""
    def assertion(dont_care_result: None) -> bool:
        return True

    return assertion
