"""Engagement, read on the on-call platform's own incident.

The platform's incident is not Argus's: they are two incidents with two ids,
opened by the same alert. Engagement is asked about the platform's incident,
found the way a person's resolution finds Argus's - by the
platform's id where an earlier match recorded it, and otherwise by the key the
monitor stamped on what it sent both - and an incident no platform incident
carries a key of is said to be exactly that, with nothing invented.

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
    Reference,
    ReportChannel,
)
from argus_incidents.repository import incidents, references
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from oncall_source import Acknowledgement, OnCallUnavailable, ReportedIncident
from oncall_source.platform import OnCallPlatform
from orchestrator.sources import the_real_sources

SOME_PLATFORM_INCIDENT = "Q2FJZEW25HFSAW"
SOME_KEY = "61118811129051d2ae8f1e4a0e1ba2b37f38f44a73bf44cb0b29ce81df1f57d3"

SOME_BEGINNING = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
SOME_ENDING = SOME_BEGINNING + timedelta(hours=1)

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
def test_engagement_finds_the_platform_incident_by_the_monitors_key_and_links_it(
    a_clean_database: None
) -> None:
    # Argus resolved it on its own, so nothing linked the two yet - but the
    # monitor paged the platform under the key it also sent Argus.
    incident_id = _an_incident_known_as(
        Reference(source="grafana", kind=NOTIFICATION_KEY, value=SOME_KEY)
    )
    platform = _a_platform_holding(SOME_PLATFORM_INCIDENT, acknowledged_after=timedelta(minutes=20))
    platform.incident_for.side_effect = (
        lambda keys: SOME_PLATFORM_INCIDENT if SOME_KEY in list(keys) else None
    )

    Scenario() \
        .when(lambda: _the_sources_over(platform).engagement(incident_id)) \
        .then(all_of(
            _the_platform_was_asked_about(platform, SOME_PLATFORM_INCIDENT),
            _it_is_now_known_as(incident_id, SOME_PLATFORM_INCIDENT)
        ))


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
    platform.incident_for.return_value = None

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
    platform.incident_for.side_effect = OnCallUnavailable("unreachable")

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
    platform.incident_for.return_value = None

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


def _it_is_now_known_as(incident_id: str, platform_incident: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        with connect_from_env() as conn:
            found = references.get_incident_by_values(conn, ON_CALL_INCIDENT,
                                                      [platform_incident])

        if found != incident_id:
            raise AssertionError(
                f"Expected [{incident_id}] linked to the platform's incident "
                f"[{platform_incident}], and that id finds [{found}]."
            )

        return True

    return assertion


def _the_answer_is(expected: object) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{answer!r}].")

        return True

    return assertion
