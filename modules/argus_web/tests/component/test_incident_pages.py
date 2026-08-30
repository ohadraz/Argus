from __future__ import annotations

import re

import psycopg
import pytest
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_web.app import app
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from orchestrator.repository import actions, hypotheses, incidents, postmortems

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

"""Argus's own screen, through the browser's door.

Nothing is stubbed: a request reaches the real app, reads through the real
repositories against a real Postgres, and comes back as the HTML a person
looking at the demo would get. The assertions are on data attributes the
templates carry deliberately - a page contract, rather than on prose, which is
free to change without any of these tests having an opinion.
"""


@pytest.mark.component
def test_the_history_lists_incidents_newest_first() -> None:
    # The history opens on what just happened. Oldest-first would put the
    # incident somebody came looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name="HighErrorRate")
    a_newer_alert = Alert(service="newer-service", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        older = incidents.create(conn, an_older_alert)
        newer = incidents.create(conn, a_newer_alert)

    listed = _attribute("incident", _get("/history"))

    assert listed.index(newer) < listed.index(older), (
        "Expected the newer incident above the older one."
    )


@pytest.mark.component
def test_the_history_links_to_each_incident() -> None:
    # A list of incidents nobody can open is a list of ids.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

    assert f'href="/incidents/{incident_id}"' in _get("/history")


@pytest.mark.component
def test_the_history_keeps_asking_for_more() -> None:
    # The demo posture is somebody watching Argus's screen for it to react. A
    # history that only lists what existed when the page was opened means the
    # incident they are waiting for never arrives.
    assert "hx-trigger" in _get("/history")


@pytest.mark.component
def test_the_polled_history_fragment_carries_the_incidents() -> None:
    # What the poll swaps in. If it did not carry the list, the page would
    # refresh itself into an empty one every two seconds.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

    assert incident_id in _attribute("incident", _get("/history/list"))


@pytest.mark.component
def test_a_time_is_shown_in_the_zone_it_is_written_in() -> None:
    # The shop's console stamps its minutes in UTC and says so. An unlabelled
    # time here reads as local, and on a screen beside that console it looks
    # like the two disagree about when the incident happened.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

    assert "UTC" in _get("/history")
    assert "UTC" in _get(f"/incidents/{incident_id}")


@pytest.mark.component
def test_an_incident_page_shows_every_candidate_in_rank_order() -> None:
    # A walk rendered without the candidates it got wrong reads as a lucky
    # guess. Rank order, because that is the order the walk tried them in.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(conn, incident_id, subject="second", rank=2)
        _a_candidate_recorded_for(conn, incident_id, subject="first", rank=1)

    page = _get(f"/incidents/{incident_id}")

    assert _attribute("subject", page) == ["first", "second"]


@pytest.mark.component
def test_an_incident_page_distinguishes_a_candidate_the_walk_never_reached() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        tried = _a_candidate_recorded_for(conn, incident_id, subject="tried", rank=1)
        _a_candidate_recorded_for(conn, incident_id, subject="never reached", rank=2)
        hypotheses.record_outcome(conn, tried, tested=True, result="confirmed")

    page = _get(f"/incidents/{incident_id}")

    assert _attribute("tested", page) == ["true", "false"]


@pytest.mark.component
def test_an_incident_page_shows_a_candidates_evidence_with_the_candidate() -> None:
    # Evidence in a dump of its own makes a reader match claims to timestamps,
    # which is the reader investigating the incident again.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(
            conn,
            incident_id,
            subject="a-flag",
            rank=1,
            evidence=["error rate rose at 10:14"],
        )

    page = _get(f"/incidents/{incident_id}")

    assert "error rate rose at 10:14" in page


@pytest.mark.component
def test_an_incident_page_shows_that_a_refuted_attempt_was_put_back() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned. A page showing the attempt without that would leave a reader
    # believing the flag is still flipped.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        refuted = _a_candidate_recorded_for(conn, incident_id, subject="first", rank=1)
        confirmed = _a_candidate_recorded_for(conn, incident_id, subject="second", rank=2)
        _an_attempt_taken_for(conn, incident_id, refuted, outcome="refuted")
        _an_attempt_taken_for(conn, incident_id, confirmed, outcome="confirmed")

    page = _get(f"/incidents/{incident_id}")

    assert _attribute("outcome", page) == ["refuted", "confirmed"]
    assert _attribute("undone", page) == ["true", "false"]


@pytest.mark.component
def test_a_running_incident_keeps_asking_for_more() -> None:
    # The point of watching it beside the shop's console: the walk moves on
    # this screen without anybody pressing refresh.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

    assert "hx-trigger" in _get(f"/incidents/{incident_id}")


@pytest.mark.component
def test_a_finished_incident_stops_asking() -> None:
    # A finished incident's page that keeps polling is a page that will still
    # be polling tomorrow.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
            actor=Actor.MITIGATION,
            action="mitigation attempted",
        )

    assert "hx-trigger" not in _get(f"/incidents/{incident_id}")


@pytest.mark.component
def test_the_polled_fragment_carries_the_walk_on_its_own() -> None:
    # What the poll swaps in. If it did not carry the walk, a page watched from
    # the first second would never show one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(conn, incident_id, subject="a-flag", rank=1)

    fragment = _get(f"/incidents/{incident_id}/walk")

    assert _attribute("subject", fragment) == ["a-flag"]


@pytest.mark.component
def test_an_unknown_incident_is_reported_as_unknown() -> None:
    # An empty page for an id that never existed invents a record.
    a_nonexistent_id = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        response = client.get(f"/incidents/{a_nonexistent_id}")

    assert response.status_code == 404, f"Expected 404, got {response.status_code}."


@pytest.mark.component
def test_a_postmortem_is_shown_on_its_own_page() -> None:
    # Its own page because it is the largest body Argus writes, and the
    # incident page beside it polls every two seconds.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            {
                "root_cause": "a-flag was enabled",
                "cost_estimate": {"dont_care": 0},
                "assumptions": ["dont care"],
                "executive_summary": "dont care",
                "checklist_complete": True,
            },
        )

    assert "a-flag was enabled" in _get(f"/incidents/{incident_id}/postmortem")


@pytest.mark.component
def test_an_incident_with_no_postmortem_says_so_rather_than_failing() -> None:
    # Most incidents have none for most of their life, and an error for the
    # ordinary case trains a reader to ignore errors.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        response = client.get(f"/incidents/{incident_id}/postmortem")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}."


@pytest.mark.component
def test_the_view_offers_no_way_to_change_anything() -> None:
    # Looking at what Argus did must not be able to alter it. The alert webhook
    # is the one route that writes, and it is not part of the view.
    read_only = {"GET", "HEAD", "OPTIONS"}
    writing_routes = [
        (route.path, sorted((route.methods or set()) - read_only))
        for route in app.routes
        if isinstance(route, APIRoute)
        and not route.path.startswith("/webhooks/")
        and (route.methods or set()) - read_only
    ]

    assert writing_routes == [], f"Expected no writing route, got {writing_routes}."


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


def _a_candidate_recorded_for(conn: psycopg.Connection,
                              incident_id: str,
                              subject: str,
                              rank: int,
                              evidence: list[str] | None = None) -> str:
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary=f"dont care - {subject}",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=evidence or [],
        subject=subject,
        rank=rank,
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _an_attempt_taken_for(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str,
                          outcome: str) -> None:
    actions.record(
        conn,
        incident_id,
        hypothesis_id=hypothesis_id,
        action_type="revert-feature-flag",
        outcome=outcome,
        undo_descriptor={"flag": "dont-care", "was_enabled": True},
    )
