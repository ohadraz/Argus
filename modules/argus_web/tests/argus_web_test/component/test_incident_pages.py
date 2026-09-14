from __future__ import annotations

import re
from http import HTTPStatus as HttpStatus
from typing import Final

import httpx
import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import (
    Alert,
    CauseType,
    Evidence,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    PostmortemDocument,
)
from argus_incidents.repository import hypotheses, incidents, postmortems, taken_actions
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient

"""Argus's own screen, through the browser's door.

Nothing is stubbed: a request reaches the real app, reads through the real
repositories against a real Postgres, and comes back as the HTML a person
looking at the demo would get. The assertions are on data attributes the
templates carry deliberately - a page contract, rather than on prose, which is
free to change without any of these tests having an opinion.
"""

# What htmx's "ask again in a moment" looks like in the rendered page. Named
# because two assertions read it and they must read the same thing: one saying
# the page polls and one saying it has stopped, disagreeing about the spelling,
# would both pass on a page that does neither.
_POLLS_FOR_MORE: Final = "hx-trigger"


@pytest.mark.component
def test_the_history_lists_incidents_newest_first() -> None:
    # The history opens on what just happened. Oldest-first would put the
    # incident somebody came looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name="HighErrorRate")
    a_newer_alert = Alert(service="newer-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        older = incidents.create(conn, an_older_alert)
        conn.commit()  # `now()` is transaction time - one transaction, one timestamp
        newer = incidents.create(conn, a_newer_alert)

    Scenario() \
        .given(
            older, newer
        ) \
        .when(
            lambda: _get("/history")
        ) \
        .then(
            _the_page_lists(newer, above=older)
        )


@pytest.mark.component
def test_the_history_links_to_each_incident() -> None:
    # A list of incidents nobody can open is a list of ids.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get("/history")
        ) \
        .then(
            _the_page_links_to(f"/incidents/{incident_id}")
        )


@pytest.mark.component
def test_the_history_keeps_asking_for_more() -> None:
    # The demo posture is somebody watching Argus's screen for it to react. A
    # history that only lists what existed when the page was opened means the
    # incident they are waiting for never arrives.
    Scenario() \
        .when(
            lambda: _get("/history")
        ) \
        .then(
            _the_page_keeps_asking()
        )


@pytest.mark.component
def test_the_polled_history_fragment_carries_the_incidents() -> None:
    # What the poll swaps in. If it did not carry the list, the page would
    # refresh itself into an empty one every two seconds.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get("/history/list")
        ) \
        .then(
            _the_page_lists_the_incident(incident_id)
        )


@pytest.mark.component
def test_a_time_is_shown_in_the_zone_it_is_written_in() -> None:
    # The shop's console stamps its minutes in UTC and says so. An unlabelled
    # time here reads as local, and on a screen beside that console it looks
    # like the two disagree about when the incident happened.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: [_get("/history"), _get(f"/incidents/{incident_id}")]
        ) \
        .then(
            _every_page_says("UTC")
        )


@pytest.mark.component
def test_an_incident_page_shows_every_candidate_in_rank_order() -> None:
    # A walk rendered without the candidates it got wrong reads as a lucky
    # guess. Rank order, because that is the order the walk tried them in.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(conn, incident_id, subject="second", rank=2)
        _a_candidate_recorded_for(conn, incident_id, subject="first", rank=1)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows("subject", "first", "second")
        )


@pytest.mark.component
def test_an_incident_page_distinguishes_a_candidate_the_walk_never_reached() -> None:
    # "Never reached" and "tried and refuted" are the difference between a walk
    # that ran out of options and one that stopped because it was right.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        tried = _a_candidate_recorded_for(conn, incident_id, subject="tried", rank=1)
        _a_candidate_recorded_for(conn, incident_id, subject="never reached", rank=2)
        hypotheses.record_outcome(conn, tried, tested=True, result="confirmed")

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows("tested", "true", "false")
        )


@pytest.mark.component
def test_an_incident_page_shows_a_candidates_evidence_with_the_candidate() -> None:
    # Evidence in a dump of its own makes a reader match claims to timestamps,
    # which is the reader investigating the incident again.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    a_cited_line = "error rate rose at 10:14"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(
            conn,
            incident_id,
            subject="a-flag",
            rank=1,
            evidence=[a_cited_line]
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_says(a_cited_line)
        )


@pytest.mark.component
def test_an_incident_page_shows_that_a_refuted_attempt_was_put_back() -> None:
    # A reversible action that did not help is undone before its verdict is
    # returned. A page showing the attempt without that would leave a reader
    # believing the flag is still flipped.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        refuted = _a_candidate_recorded_for(conn, incident_id, subject="first", rank=1)
        confirmed = _a_candidate_recorded_for(conn, incident_id, subject="second", rank=2)
        _an_attempt_taken_for(conn, incident_id, refuted, outcome="refuted")
        _an_attempt_taken_for(conn, incident_id, confirmed, outcome="confirmed")

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            _the_page_shows("outcome", "refuted", "confirmed"),
            _the_page_shows("undone", "true", "false")
        ))


@pytest.mark.component
def test_a_running_incident_keeps_asking_for_more() -> None:
    # The point of watching it beside the shop's console: the walk moves on
    # this screen without anybody pressing refresh.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_keeps_asking()
        )


@pytest.mark.component
def test_a_finished_incident_stops_asking() -> None:
    # A finished incident's page that keeps polling is a page that will still
    # be polling tomorrow.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_has_stopped_asking()
        )


@pytest.mark.component
def test_the_polled_fragment_carries_the_walk_on_its_own() -> None:
    # What the poll swaps in. If it did not carry the walk, a page watched from
    # the first second would never show one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_candidate_recorded_for(conn, incident_id, subject="a-flag", rank=1)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}/walk")
        ) \
        .then(
            _the_page_shows("subject", "a-flag")
        )


@pytest.mark.component
def test_an_unknown_incident_is_reported_as_unknown() -> None:
    # An empty page for an id that never existed invents a record.
    a_nonexistent_id = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .given(
                a_nonexistent_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{a_nonexistent_id}")
            ) \
            .then(
                _the_answer_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_a_postmortem_is_shown_on_its_own_page() -> None:
    # Its own page because it is the largest body Argus writes, and the
    # incident page beside it polls every two seconds.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    a_root_cause = "a-flag was enabled"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=a_root_cause,
                executive_summary="dont care",
                customer_loss_estimate=None,
                estimate_currency="usd",
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=["dont care"],
                checklist_complete=True
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_says(a_root_cause)
        )


@pytest.mark.component
def test_an_incident_with_no_postmortem_says_so_rather_than_failing() -> None:
    # Most incidents have none for most of their life, and an error for the
    # ordinary case trains a reader to ignore errors.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem")
            ) \
            .then(
                _the_answer_was(HttpStatus.OK)
            )


@pytest.mark.component
def test_a_running_incident_can_be_withdrawn_from_its_page() -> None:
    # The first button anybody wants during an incident, and the only thing on
    # this screen that acts rather than reports.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            _the_page_says(f"/incidents/{incident_id}/withdraw"),
            _the_page_shows("withdraw", incident_id)
        ))


@pytest.mark.component
def test_a_finished_incident_offers_no_way_to_withdraw_it() -> None:
    # Nothing to stop. Offering it would invite somebody to take back a
    # mitigation that is holding the service up, and the answer would be a 409
    # they had no reason to expect.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(
            conn,
            incident_id,
            IncidentStatus.RESOLVED,
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows_no("withdraw")
        )


@pytest.mark.component
def test_the_postmortem_page_says_how_many_responded_and_what_they_were() -> None:
    # Minutes alone read as one person's night. The count is what makes them
    # person-minutes on the page as well as in the row, and the titles are the
    # part a reader can act on - a senior engineer and an SRE spending two
    # hours is a different sentence from "120".
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_minutes = 88
    some_responders = 2
    some_title = "Principal Kuki Buki"
    some_other_title = "Senior Shuki Tuki"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause="dont care",
                executive_summary="dont care",
                customer_loss_estimate=None,
                estimate_currency="usd",
                engineer_minutes=some_minutes,
                responders=some_responders,
                responder_titles=[some_title, some_other_title],
                tokens_spent=None,
                assumptions=["dont care"],
                checklist_complete=True
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: _get(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            _the_page_says(str(some_minutes)),
            _the_page_says(str(some_responders)),
            _the_page_says(some_title),
            _the_page_says(some_other_title)
        ))


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


def _the_page_shows(attribute: str, *values: str) -> Assertion[str]:
    """Exactly these values of one `data-` attribute, in this order."""
    def assertion(page: str) -> bool:
        shown = _attribute(attribute, page)

        if shown != list(values):
            raise AssertionError(
                f"Expected [{attribute}] to be {list(values)}, got {shown}."
            )

        return True

    return assertion


def _the_page_shows_no(attribute: str) -> Assertion[str]:
    """That one `data-` attribute is absent altogether.

    Its own assertion rather than an empty `_the_page_shows`, because "shows
    nothing" is the claim being made, and a call with no values to show reads
    as one somebody forgot to finish.
    """
    def assertion(page: str) -> bool:
        shown = _attribute(attribute, page)

        if shown:
            raise AssertionError(f"Expected no [{attribute}] at all, got {shown}.")

        return True

    return assertion


def _the_page_lists(this: str, above: str) -> Assertion[str]:
    """That one incident is shown before another, wherever the rest of the
    history put them.

    Relative rather than positional: this page is every incident there has ever
    been, so an assertion pinning the positions would be an assertion about
    whatever the tests before it left behind.
    """
    def assertion(page: str) -> bool:
        listed = _attribute("incident", page)

        for incident_id in (this, above):
            if incident_id not in listed:
                raise AssertionError(
                    f"Expected [{incident_id}] to be listed at all, got {listed}."
                )

        if listed.index(this) > listed.index(above):
            raise AssertionError(
                f"Expected [{this}] above [{above}], the order was {listed}."
            )

        return True

    return assertion


def _the_page_lists_the_incident(incident_id: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        listed = _attribute("incident", page)

        if incident_id not in listed:
            raise AssertionError(f"Expected [{incident_id}] to be listed, got {listed}.")

        return True

    return assertion


def _the_page_says(text: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if text not in page:
            raise AssertionError(f"Expected the page to say [{text}], it did not.")

        return True

    return assertion


def _every_page_says(text: str) -> Assertion[list[str]]:
    """The same claim against more than one page, named rather than repeated.

    A time is written in a zone on every screen that shows one, so the test is
    about the pages together - and asserting it of one page at a time would
    pass while the other read as local.
    """
    def assertion(pages: list[str]) -> bool:
        silent = [number for number, page in enumerate(pages, start=1) if text not in page]

        if silent:
            raise AssertionError(f"Expected every page to say [{text}], {silent} did not.")

        return True

    return assertion


def _the_page_links_to(href: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if f'href="{href}"' not in page:
            raise AssertionError(f"Expected the page to link to [{href}], it did not.")

        return True

    return assertion


def _the_page_keeps_asking() -> Assertion[str]:
    def assertion(page: str) -> bool:
        if _POLLS_FOR_MORE not in page:
            raise AssertionError("Expected the page to keep asking for more, it did not.")

        return True

    return assertion


def _the_page_has_stopped_asking() -> Assertion[str]:
    def assertion(page: str) -> bool:
        if _POLLS_FOR_MORE in page:
            raise AssertionError("Expected the page to have stopped asking, it had not.")

        return True

    return assertion


def _the_answer_was(expected: HttpStatus) -> Assertion[httpx.Response]:
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected:
            raise AssertionError(
                f"Expected [{expected}], got [{response.status_code}]: {response.text}."
            )

        return True

    return assertion


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
        supporting_evidence=[Evidence(claim=cited, at=None) for cited in evidence or []],
        subject=subject,
        rank=rank,
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _an_attempt_taken_for(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str,
                          outcome: str) -> None:
    taken_actions.record(
        conn,
        incident_id,
        hypothesis_id=hypothesis_id,
        action_type="revert-feature-flag",
        outcome=outcome,
        undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True)
    )
