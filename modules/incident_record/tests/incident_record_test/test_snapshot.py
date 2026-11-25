"""One incident read whole, every part of it once.

What the snapshot owes its reader is each part exactly as the roles read it on
the same connection - its row, its account, its candidates, its actions, its
leads, and the first chat thread it was told of in - and nothing for an incident
there is none of.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, calling, the_answer_was
from core.events import AgentInvoked
from core.models import CHAT_THREAD, Actor, Alert, FailureMode, Hypothesis, Reference
from incident_record import (
    IncidentSnapshot,
    incident_names_on,
    incident_reads_on,
    the_snapshot_of,
)
from incident_record.repository import events, hypotheses
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
DONT_CARE_SUMMARY = "a feature flag was toggled on just before the errors began"
DONT_CARE_CONFIDENCE = 0.9
SOME_CHAT_PLATFORM = "Slack"
SOME_THREAD = "C0123456789/1700000000.000100"
# An incident no row was ever written for.
NO_SUCH_INCIDENT = "00000000-0000-4000-8000-000000000000"


@pytest.mark.component
def test_a_snapshot_holds_each_part_as_the_roles_read_it() -> None:
    # A line, a candidate and a thread, so that a part read from the wrong
    # place reads as something other than empty.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

        Scenario() \
            .given(
                calling(lambda: events.record(
                    conn, AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR))),
                calling(lambda: hypotheses.record(conn, _a_candidate_of(incident_id))),
                calling(lambda: incident_names_on(conn).give(incident_id, [
                    Reference(source=SOME_CHAT_PLATFORM, kind=CHAT_THREAD, value=SOME_THREAD)
                ]))
            ) \
            .when(
                lambda: the_snapshot_of(conn, incident_id)
            ) \
            .then(
                _each_part_is_as_read_on(conn, incident_id)
            )


@pytest.mark.component
def test_a_snapshot_of_an_incident_told_of_in_no_thread_holds_no_thread() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

        Scenario() \
            .when(
                lambda: the_snapshot_of(conn, incident_id)
            ) \
            .then(
                _the_thread_is_none()
            )


@pytest.mark.component
def test_an_incident_nobody_opened_has_no_snapshot() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .when(
                lambda: the_snapshot_of(conn, NO_SUCH_INCIDENT)
            ) \
            .then(
                the_answer_was(None)
            )


def _a_candidate_of(incident_id: str) -> Hypothesis:
    return Hypothesis(incident_id=incident_id,
                      summary=DONT_CARE_SUMMARY,
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                      confidence=DONT_CARE_CONFIDENCE,
                      supporting_evidence=[])


def _each_part_is_as_read_on(conn: psycopg.Connection,
                             incident_id: str) -> Assertion[IncidentSnapshot | None]:
    """That the snapshot is the roles' own reads of the incident on `conn`, the
    thread a non-empty one."""
    def assertion(snapshot: IncidentSnapshot | None) -> bool:
        reads = incident_reads_on(conn)
        incident = reads.incident(incident_id)
        thread = incident_names_on(conn).first_of_kind(incident_id, CHAT_THREAD)
        expected = None if incident is None else IncidentSnapshot(
            incident=incident,
            account=reads.account(incident_id),
            candidates=reads.candidates(incident_id),
            actions=reads.actions(incident_id),
            leads=reads.leads(incident_id),
            chat_thread=thread
        )

        if thread is None or snapshot != expected:
            raise AssertionError(
                f"Expected the snapshot to hold each part as the roles read it, the thread "
                f"[{SOME_THREAD}] among them: {expected}. Got {snapshot}."
            )

        return True

    return assertion


def _the_thread_is_none() -> Assertion[IncidentSnapshot | None]:
    def assertion(snapshot: IncidentSnapshot | None) -> bool:
        if snapshot is None or snapshot.chat_thread is not None:
            raise AssertionError(
                f"Expected a snapshot holding no chat thread, got {snapshot}."
            )

        return True

    return assertion
