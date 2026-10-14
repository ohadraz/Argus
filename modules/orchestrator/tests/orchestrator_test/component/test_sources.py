"""Engagement, read on the on-call platform's own incident.

The platform's incident is not Argus's: they are two incidents with two ids,
opened by the same alert. Engagement is asked about the platform's incident,
found the way a person's resolution finds Argus's - by the platform's id where
an earlier match recorded it, and otherwise by the key the monitor stamped on
what it sent both - and an incident no platform incident carries a key of is
said to be exactly that, with nothing invented.

A key does not name one platform incident. Every firing of an alert group pages
under the group's one key, so the platform holds a page for each firing, and
the one this incident is about is the one open while it was going on. Where
more than one was, nothing here can say which minutes were spent on this
incident, and it says so rather than pick.

The platform is stood in for, because it is somebody else's API; the names an
incident is known by are real rows, because finding them is the question.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import call, create_autospec

import pytest
from agent_postmortem import EngagementAnswer, NotPaged, Sources
from argus_core import connect_from_env, get_settings
from argus_core.anomaly import AnomalyThresholds
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    Alert,
    Lifespan,
    Reference,
    ReportChannel,
)
from argus_incidents.repository import incidents, references
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from oncall_source import Acknowledgement, OnCallUnavailable, ReportedIncident
from oncall_source.platform import OnCallPlatform, PagedIncident
from orchestrator.sources import the_real_sources

SOME_PLATFORM_INCIDENT = "Q2FJZEW25HFSAW"
SOME_OTHER_PLATFORM_INCIDENT = "Q0N5RRK7RT1Q46"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

SOME_BEGINNING = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
SOME_ENDING = SOME_BEGINNING + timedelta(hours=1)
A_DAY = timedelta(days=1)

DONT_CARE_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)


@pytest.mark.component
def test_engagement_is_read_on_the_platform_incident_an_earlier_match_linked(
    a_clean_database: None
) -> None:
    # A person resolved it in the platform, which is when the two were linked.
    incident_id = _an_incident_known_as(
        Reference(source="pagerduty", kind=ON_CALL_INCIDENT, value=SOME_PLATFORM_INCIDENT)
    )
    some_wait = timedelta(minutes=20)
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=some_wait)

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_platform_was_asked_about(platform, SOME_PLATFORM_INCIDENT),
            _engaged_for(minutes=(SOME_ENDING - SOME_BEGINNING - some_wait) // timedelta(minutes=1))
        ))


@pytest.mark.component
def test_a_page_another_incident_is_linked_to_is_said_to_be_shared(
    a_clean_database: None
) -> None:
    # Argus said it mitigated the first incident and the alarm went on, so a
    # second followed, and the platform kept one page open across both. Each
    # write-up reports that page's whole response, and says how many others
    # it was also theirs.
    platform_link = Reference(source="pagerduty", kind=ON_CALL_INCIDENT,
                              value=SOME_PLATFORM_INCIDENT)
    _an_incident_known_as(platform_link)
    incident_id = _an_incident_known_as(platform_link)
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(_shared_with(1))


@pytest.mark.component
def test_a_page_no_other_incident_is_linked_to_is_this_incidents_alone(
    a_clean_database: None
) -> None:
    incident_id = _an_incident_known_as(
        Reference(source="pagerduty", kind=ON_CALL_INCIDENT, value=SOME_PLATFORM_INCIDENT)
    )
    _an_incident_known_as(
        Reference(source="pagerduty", kind=ON_CALL_INCIDENT, value=SOME_OTHER_PLATFORM_INCIDENT)
    )
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(_shared_with(0))


@pytest.mark.component
def test_engagement_finds_the_platform_incident_by_the_monitors_key_and_links_it(
    a_clean_database: None
) -> None:
    # Argus ended it on its own, so nothing linked the two yet - but the
    # monitor paged the platform under the key it also sent Argus.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.side_effect = lambda keys: (
        [_a_page(SOME_PLATFORM_INCIDENT, opened_at=_the_start_of(incident_id), resolved_at=None)]
        if SOME_KEY in list(keys) else []
    )

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_platform_was_asked_about(platform, SOME_PLATFORM_INCIDENT),
            _it_is_now_known_as(incident_id, SOME_PLATFORM_INCIDENT)
        ))


@pytest.mark.component
def test_of_the_pages_under_the_key_the_one_open_during_the_incident_is_its_own(
    a_clean_database: None
) -> None:
    # The alert fired last week too, under the same key, and that page closed
    # when its alert stopped. Last week's minutes are last week's incident's.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    began = _the_start_of(incident_id)
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.return_value = [
        _a_page(SOME_OTHER_PLATFORM_INCIDENT, opened_at=began - 7 * A_DAY,
                resolved_at=began - 6 * A_DAY),
        _a_page(SOME_PLATFORM_INCIDENT, opened_at=began, resolved_at=None)
    ]

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_platform_was_asked_about(platform, SOME_PLATFORM_INCIDENT),
            _it_is_now_known_as(incident_id, SOME_PLATFORM_INCIDENT)
        ))


@pytest.mark.component
def test_an_incident_two_pages_under_its_key_were_open_for_cannot_say(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing here can say which page's minutes were spent on this incident,
    # and summing them would count one response twice. "Could not say", and
    # linked to neither.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    began = _the_start_of(incident_id)
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.return_value = [
        _a_page(SOME_OTHER_PLATFORM_INCIDENT, opened_at=began, resolved_at=None),
        _a_page(SOME_PLATFORM_INCIDENT, opened_at=began, resolved_at=None)
    ]

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_answer_is(None),
            _it_is_linked_to_no_platform_incident(incident_id),
            one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                  "several on-call incidents match")
        ))


@pytest.mark.component
def test_pages_under_the_key_that_closed_before_the_incident_began_were_not_its_page(
    a_clean_database: None
) -> None:
    # Only last week's firing paged anybody. This incident was not paged for,
    # and last week's page is not evidence that it was.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    began = _the_start_of(incident_id)
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.return_value = [
        _a_page(SOME_PLATFORM_INCIDENT, opened_at=began - 7 * A_DAY,
                resolved_at=began - 6 * A_DAY)
    ]

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(_the_answer_is(NotPaged()))


@pytest.mark.component
def test_an_incident_no_platform_incident_carries_a_key_of_was_not_paged(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # Not "nobody engaged" - nobody was asked to - and not "could not say" -
    # the platform answered. Said as what it is, with no minutes invented.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.return_value = []

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_answer_is(NotPaged()),
            one_record_was_logged(caplog, "orchestrator.sources", logging.INFO,
                                  "no on-call incident linked")
        ))


@pytest.mark.component
def test_without_an_on_call_platform_who_responded_cannot_be_said(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    # "Could not say", never "not paged": nobody looked. But the platform is
    # optional, and a deployment that chose not to have one is not at fault, so
    # it is said as information rather than as a warning on every write-up.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _the_sources_over(None).engagement(incident_id)) \
        .then(all_of(
            _the_answer_is(None),
            one_record_was_logged(caplog, "orchestrator.sources", logging.INFO,
                                  "no on-call platform configured")
        ))


@pytest.mark.component
def test_a_platform_that_cannot_be_read_while_finding_its_incident_cannot_say(
    a_clean_database: None, caplog: pytest.LogCaptureFixture
) -> None:
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incidents_for.side_effect = OnCallUnavailable("unreachable")

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_answer_is(None),
            one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                  "engagement could not be read",
                                  failure=OnCallUnavailable)
        ))


def _an_incident_known_as(reference: Reference) -> str:
    with connect_from_env() as conn:
        incident_id = incidents.create(conn, Alert(service="kuki-service",
                                                   alert_name="HighErrorRate"))
        references.add(conn, incident_id, [reference])
        conn.commit()

    return incident_id


def _the_start_of(incident_id: str) -> datetime:
    """When the incident began, by the database's clock - the moment the
    monitor paged the platform for it, near enough."""
    with connect_from_env() as conn:
        incident = incidents.get(conn, incident_id)

    assert incident is not None

    return incident.created_at


def _a_page(platform_incident: str,
            opened_at: datetime,
            resolved_at: datetime | None) -> PagedIncident:
    return PagedIncident(id=platform_incident,
                         lifespan=Lifespan(began_at=opened_at, ended_at=resolved_at))


def _a_platform_holding(platform_incident: str, acknowledged_after: timedelta) -> Any:
    """A platform holding one incident, acknowledged once, by one person."""
    platform = create_autospec(OnCallPlatform, instance=True)
    platform.channel = ReportChannel.PAGERDUTY
    platform.reported_incident.return_value = ReportedIncident(
        began_at=SOME_BEGINNING,
        ended_at=SOME_ENDING,
        acknowledgements=[Acknowledgement(at=SOME_BEGINNING + acknowledged_after,
                                          responder_id="some-responder",
                                          job_title=None)]
    )
    platform.incidents_for.return_value = []

    return platform


def _the_sources_over(platform: Any) -> Sources:
    return the_real_sources(get_settings(), connect_from_env,
                            create_autospec(McpClient, instance=True),
                            DONT_CARE_THRESHOLDS,
                            oncall=platform)


def _the_platform_was_asked_about(platform: Any, platform_incident: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if platform.reported_incident.call_args_list != [call(platform_incident)]:
            raise AssertionError(
                f"Expected engagement read on the platform's incident "
                f"[{platform_incident}], got {platform.reported_incident.call_args_list}."
            )

        return True

    return assertion


def _engaged_for(minutes: int) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if not isinstance(answer, EngagementAnswer) or answer.minutes != minutes:
            raise AssertionError(f"Expected [{minutes}] engaged minutes, got [{answer!r}].")

        return True

    return assertion


def _shared_with(others: int) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if not isinstance(answer, EngagementAnswer) or answer.shared_with != others:
            raise AssertionError(
                f"Expected an engagement read on a page [{others}] other incidents "
                f"shared, got [{answer!r}]."
            )

        return True

    return assertion


def _it_is_now_known_as(incident_id: str, platform_incident: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        with connect_from_env() as conn:
            found = [incident.id for incident in references.get_incidents_by_values(
                conn, ON_CALL_INCIDENT, [platform_incident]
            )]

        if found != [incident_id]:
            raise AssertionError(
                f"Expected [{incident_id}] linked to the platform's incident "
                f"[{platform_incident}], and that id finds {found}."
            )

        return True

    return assertion


def _it_is_linked_to_no_platform_incident(incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        with connect_from_env() as conn:
            linked = references.get_values_for(conn, incident_id, ON_CALL_INCIDENT)

        if linked:
            raise AssertionError(
                f"Expected [{incident_id}] linked to no platform incident, got {linked}."
            )

        return True

    return assertion


def _the_answer_is(expected: object) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{answer!r}].")

        return True

    return assertion
