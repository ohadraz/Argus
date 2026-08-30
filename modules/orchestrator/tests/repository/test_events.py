from __future__ import annotations

import psycopg
import pytest
from argus_core.events import (
    AgentInvoked,
    IncidentEvent,
    LogsRetrieved,
    OnsetDetected,
    RetrievalChannel,
    RetrievalRequested,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from orchestrator.repository import events, incidents

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

"""The account of an incident, written down and read back.

This is the only writer the event stream has, and it writes nothing else. What
it stores has to come back as what went in - the same type, the same payload,
in the same order - because the narration is not re-derivable from anything
else: if a line is lost here it is lost.
"""


@pytest.mark.integration
def test_a_recorded_event_comes_back_as_the_kind_it_was_published_as() -> None:
    # A reader holding a dictionary has to match on strings to work out what it
    # is looking at, which is the reader doing the discriminating that the
    # publisher already did.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        events.record(conn, OnsetDetected(incident_id=incident_id,
                                          onset="2026-08-30T10:03:00Z"))

        recorded = events.get_by_incident(conn, incident_id)

    assert isinstance(recorded[0], OnsetDetected)
    assert recorded[0].onset == "2026-08-30T10:03:00Z"


@pytest.mark.integration
def test_events_come_back_in_the_order_they_were_published() -> None:
    # The narration is a sequence, and out of order it describes a different
    # investigation - one that read the logs before deciding where to look.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        for event in _an_investigation_in_three_steps(incident_id):
            events.record(conn, event)

        kinds = [event.kind for event in events.get_by_incident(conn, incident_id)]

    assert kinds == ["agent-invoked", "retrieval-requested", "logs-retrieved"]


@pytest.mark.integration
def test_a_payload_comes_back_whole() -> None:
    # The reason the payload is stored at all: the page shows what Argus read,
    # and a line dropped on the way in is a line nobody can ever show.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_lines_it_read = [
        "2026-08-30T10:03:00Z ERROR io-shop: division by zero",
        "2026-08-30T10:03:00Z WARN io-shop: retrying",
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        events.record(conn, LogsRetrieved(
            incident_id=incident_id,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            lines=the_lines_it_read,
        ))

        recorded = events.get_by_incident(conn, incident_id)

    assert isinstance(recorded[0], LogsRetrieved)
    assert recorded[0].lines == the_lines_it_read


@pytest.mark.integration
def test_an_incident_that_published_nothing_reads_as_empty() -> None:
    # An incident whose components never published is a real incident with no
    # story, which is not an error and not a missing incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

        assert events.get_by_incident(conn, incident_id) == []


@pytest.mark.integration
def test_only_one_incident_s_events_come_back() -> None:
    # Two incidents can run against one database, and a narration that mixed
    # them would read as one investigation contradicting itself.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        another_incident_id = incidents.create(conn, some_alert)
        events.record(conn, AgentInvoked(incident_id=incident_id,
                                         agent=Actor.INVESTIGATOR))
        events.record(conn, AgentInvoked(incident_id=another_incident_id,
                                         agent=Actor.MITIGATION))

        recorded = events.get_by_incident(conn, incident_id)

    assert [event.incident_id for event in recorded] == [incident_id]


@pytest.mark.integration
def test_recording_an_event_writes_nothing_else() -> None:
    # The single-writer rule (spec §7.1) survives this table's arrival: the
    # subscriber writes events, and the incident's own state keeps the one
    # writer it already had.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        before = _row_counts(conn)

        events.record(conn, AgentInvoked(incident_id=incident_id,
                                         agent=Actor.INVESTIGATOR))

        assert _row_counts(conn) == before


def _an_investigation_in_three_steps(incident_id: str) -> list[IncidentEvent]:
    return [
        AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR),
        RetrievalRequested(
            incident_id=incident_id,
            channel=RetrievalChannel.LOGS,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
        ),
        LogsRetrieved(
            incident_id=incident_id,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            lines=["some log line"],
        ),
    ]


def _row_counts(conn: psycopg.Connection) -> dict[str, int]:
    counted = {}
    with conn.cursor() as cursor:
        for table in ("incident", "hypothesis", "action", "timeline_event"):
            cursor.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
            row = cursor.fetchone()
            assert row is not None
            counted[table] = row[0]

    return counted
