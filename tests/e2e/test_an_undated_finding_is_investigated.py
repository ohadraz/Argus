"""A finding nobody can date, end to end.

The stale cache again - a standby that had stopped copying was promoted in front
of shoppers - except that nothing recorded when. The shop's own check still finds
the stale entries, so it can say what is wrong; it cannot say since when, so the
page it sends carries a finding and no onset.

No series departs in this incident, so nothing can be measured to date it either,
and the walk has to be anchored on something. The only minute anybody recorded is
the one the alarm went off in: that is where to look from, and not when this
began. Nothing in the window contradicts a finding that no series carries, so the
investigation goes on rather than closing the alarm as disproven - and it ends
where the dated walk does, with the stale entries discarded.
"""

from __future__ import annotations

import httpx2
import pytest
from argus_core import parse_iso
from argus_core.events import ActionTaken, AlertAcknowledged, OnsetDetected
from argus_core.models import DISCARD_CACHE_ENTRIES, FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_UNDATED_STATE_DIVERGENCE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_wrote_a_postmortem,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events


@pytest.mark.e2e
def test_a_finding_nobody_can_date_is_walked_from_the_minute_it_paged() -> None:
    # Raised by the shop rather than built here, for the reason the dated case
    # gives: the alert carries a finding only the shop's own check can produce.
    # The scenario's id is also the recording's name.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(RECORDED_UNDATED_STATE_DIVERGENCE)),
            calling(the_model_answers_from(RECORDED_UNDATED_STATE_DIVERGENCE))
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    _the_walk_was_dated_from_the_minute_the_undated_alert_fired(),
                    cause_identified_as(FailureMode.STATE_DIVERGENCE),
                    _the_action_that_ended_it_was_a_discard_of(THE_SERVICE_NAME),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_walk_was_dated_from_the_minute_the_undated_alert_fired(
) -> Assertion[httpx2.Response]:
    """Two things Argus holds, compared against each other.

    Both halves are asserted, because the comparison alone would pass for a dated
    alert whose stated onset happened to fall in the minute it fired.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        recorded = the_incidents_events(incident_id)
        alerts = [
            event.alert for event in recorded if isinstance(event, AlertAcknowledged)
        ]
        published = [
            event.onset for event in recorded if isinstance(event, OnsetDetected)
        ]

        if not alerts:
            raise AssertionError(
                f"Incident [{incident_id}] acknowledged no alert, so there is "
                f"nothing to say what it was told."
            )

        if alerts[0].stated_onset is not None:
            raise AssertionError(
                f"The alert Argus stored for incident [{incident_id}] states the "
                f"onset [{alerts[0].stated_onset}], so this is the dated walk and "
                f"says nothing about one that had to anchor itself."
            )

        if alerts[0].started_at is None:
            raise AssertionError(
                f"The alert Argus stored for incident [{incident_id}] says nothing "
                f"about when it fired, so there is no minute to anchor on."
            )

        if not published:
            raise AssertionError(
                f"Incident [{incident_id}] published no onset, so the walk never "
                f"anchored itself - every window it read was anchored on nothing."
            )

        fired = alerts[0].started_at.replace(second=0, microsecond=0)

        if parse_iso(published[0]) != fired:
            raise AssertionError(
                f"Incident [{incident_id}] is anchored on [{published[0]}] where "
                f"its alert fired at [{fired}]. A minute nobody recorded was "
                f"invented from somewhere - most likely the first row the metrics "
                f"source happens to reach back to."
            )

        return True

    return assertion


def _the_action_that_ended_it_was_a_discard_of(
    service: str
) -> Assertion[httpx2.Response]:
    """The last action, addressed to the service the alert named."""
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing was "
                f"ever put to the question."
            )

        if (
            taken[-1].action_type != DISCARD_CACHE_ENTRIES
            or taken[-1].subject != service
        ):
            raise AssertionError(
                f"Expected the last action to be a discard addressed to "
                f"[{service}], and what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]}."
            )

        return True

    return assertion
