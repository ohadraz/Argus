from __future__ import annotations

import re

import psycopg
import pytest
from argus_core.events import (
    AlertAcknowledged,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_web.app import app
from fastapi.testclient import TestClient
from orchestrator.repository import events, incidents

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

"""The front door: what is happening now, as a browser gets it.

Nothing is stubbed. A request reaches the real app, reads the events the real
repository recorded against a real Postgres, and comes back as the HTML a
person watching the demo beside the shop's console would be looking at. The
assertions are on data attributes the templates carry deliberately - a page
contract - rather than on prose, which is free to change without any of these
tests having an opinion.
"""


@pytest.mark.component
def test_the_front_page_says_when_nothing_is_happening() -> None:
    # Argus is idle most of the time, and a screen left open during a demo has
    # to say that rather than show an empty frame that reads as broken.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)

    assert _attribute("idle", _get("/")) == ["true"]


@pytest.mark.component
def test_the_front_page_keeps_asking_so_an_incident_arrives_on_its_own() -> None:
    # Somebody opens this screen before staging the scenario. If the page only
    # showed what existed when it was opened, the incident they are waiting for
    # would never appear.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)

    assert "hx-trigger" in _get("/")


@pytest.mark.component
def test_the_front_page_shows_the_incident_that_has_not_finished() -> None:
    # Not simply the newest: an incident that resolved after this one opened
    # has nothing left to watch, and the one still running is the only thing
    # anybody came to this page for.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        still_running = incidents.create(conn, _an_alert("running-service"))
        already_finished = incidents.create(conn, _an_alert("finished-service"))
        _finished(conn, already_finished)

    assert _attribute("live-incident", _get("/")) == [still_running]


@pytest.mark.component
def test_with_nothing_running_the_front_page_shows_the_newest_one_as_finished() -> None:
    # A resolved incident vanishing the moment it resolves would take it off
    # the screen exactly when everyone in the room is looking at it.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _finished(conn, incident_id)

    page = _get("/")

    assert _attribute("live-incident", page) == [incident_id]
    assert _attribute("running", page) == ["false"]


@pytest.mark.component
def test_the_front_page_narrates_what_argus_did_in_the_order_it_did_it() -> None:
    # The account is a sequence. A page that reordered it would be telling a
    # different story from the one that was recorded.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _recorded(conn, AlertAcknowledged(incident_id=incident_id, alert=_an_alert("io-shop")))
        _recorded(conn, OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:14Z"))
        _recorded(conn, _a_hypothesis_formed_for(incident_id))

    assert _attribute("line", _get("/")) == [
        "alert-acknowledged",
        "onset-detected",
        "hypothesis-formed",
    ]


@pytest.mark.component
def test_a_metrics_retrieval_is_shown_as_a_table_with_the_bad_minutes_marked() -> None:
    # The shop's console reddens the same minutes. Two screens side by side in
    # a demo that mark different ones make a reader translate between them.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _recorded(
            conn,
            MetricsRetrieved(
                incident_id=incident_id,
                window_start="2026-08-30T10:12Z",
                window_end="2026-08-30T10:14Z",
                buckets=[
                    _a_bucket("2026-08-30T10:12Z", error_rate=0.01),
                    _a_bucket("2026-08-30T10:14Z", error_rate=0.31),
                ],
            ),
        )

    page = _get("/")

    assert _attribute("bucket", page) == ["2026-08-30T10:12Z", "2026-08-30T10:14Z"]
    assert _attribute("elevated", page) == ["false", "true"]


@pytest.mark.component
def test_a_log_retrieval_is_shown_with_its_levels_distinguished() -> None:
    # Warnings and errors apart from the rest, at a glance, in a page somebody
    # is scanning while the incident is still running.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _recorded(
            conn,
            LogsRetrieved(
                incident_id=incident_id,
                window_start="2026-08-30T10:12Z",
                window_end="2026-08-30T10:14Z",
                lines=[
                    "2026-08-30T10:12Z INFO io-shop: account page rendered",
                    "2026-08-30T10:13Z WARN io-shop: account page error rate at 6%",
                    "2026-08-30T10:14Z ERROR io-shop: account page request failed",
                ],
            ),
        )

    assert _attribute("level", _get("/")) == ["info", "warn", "error"]


@pytest.mark.component
def test_the_evidence_shown_is_the_evidence_that_was_read() -> None:
    # Byte for byte, out of the event. A page that re-fetched at render time
    # would show what the log store says now rather than what Argus saw.
    a_line_that_was_read = "2026-08-30T10:14Z ERROR io-shop: account page request failed"

    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _recorded(
            conn,
            LogsRetrieved(
                incident_id=incident_id,
                window_start="2026-08-30T10:12Z",
                window_end="2026-08-30T10:14Z",
                lines=[a_line_that_was_read],
            ),
        )

    assert a_line_that_was_read in _get("/")


@pytest.mark.component
def test_the_front_page_reaches_the_history_and_the_incidents_own_page() -> None:
    # Both without knowing a URL: somebody watching the live page is one click
    # from an older incident, and one click from this one's whole walk.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))

    page = _get("/")

    assert 'href="/history"' in page
    assert f'href="/incidents/{incident_id}"' in page


@pytest.mark.component
def test_the_polled_live_fragment_carries_the_incident_on_its_own() -> None:
    # What the poll swaps in. If it did not carry the incident, a page opened
    # before the alert arrived would refresh itself into an empty one forever.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))

    assert _attribute("live-incident", _get("/now")) == [incident_id]


@pytest.mark.component
def test_an_incidents_own_page_narrates_it_too() -> None:
    # The account of a finished incident is the point of recording one. A
    # narration only reachable while the incident is still running would be a
    # replay log nobody can replay.
    with psycopg.connect(DATABASE_URL) as conn:
        _no_incidents_at_all(conn)
        incident_id = incidents.create(conn, _an_alert("io-shop"))
        _recorded(conn, OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:14Z"))
        _finished(conn, incident_id)

    assert _attribute("line", _get(f"/incidents/{incident_id}")) == ["onset-detected"]


def _get(path: str) -> str:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == 200, (
        f"Expected 200 from {path}, got {response.status_code}."
    )

    return response.text


def _attribute(name: str, html: str) -> list[str]:
    """Every value of one `data-` attribute, in the order the document carries
    them - which is the order a reader sees."""
    return re.findall(rf'data-{name}="([^"]*)"', html)


def _no_incidents_at_all(conn: psycopg.Connection) -> None:
    """An empty database, which is the one state the front page's rule cannot
    be set up into by adding a row.

    "The newest incident, running or not" is a question about every incident
    there is, so a test about what the page does with none of them has to be
    the only incident there is - none.
    """
    with conn.cursor() as cursor:
        cursor.execute("TRUNCATE incident CASCADE")
    conn.commit()


def _finished(conn: psycopg.Connection, incident_id: str) -> None:
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
        actor=Actor.MITIGATION,
        action="dont care",
    )


def _recorded(conn: psycopg.Connection, event: IncidentEvent) -> None:
    events.record(conn, event)


def _an_alert(service: str) -> Alert:
    return Alert(service=service, alert_name="HighErrorRate")


def _a_bucket(bucket_id: str, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=error_rate,
        p50_ms=120,
        p95_ms=240,
        request_volume=200,
    )


def _a_hypothesis_formed_for(incident_id: str) -> HypothesisFormed:
    return HypothesisFormed(
        incident_id=incident_id,
        hypothesis_id="00000000-0000-0000-0000-0000000000aa",
        summary="dont care",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        subject="dont-care-flag",
        rank=1,
    )
