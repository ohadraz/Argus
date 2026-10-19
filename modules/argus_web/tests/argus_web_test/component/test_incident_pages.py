"""Argus's own screen, through the browser's door.

Nothing is stubbed: a request reaches the real app, reads through the real
repositories against a real Postgres, and comes back as the HTML a person
looking at the demo would get. The assertions are on data attributes the
templates carry deliberately - a page contract, rather than on prose, which is
free to change without any of these tests having an opinion.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus as HttpStatus

import httpx2
import psycopg
import pytest
from argus_core import connect_from_env, new_id
from argus_core.events import CandidateSelected, ChangesRetrieved, StatusChanged
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    AlarmClaim,
    Alert,
    ChainStep,
    ChangeEvent,
    ChangeKind,
    CitedChange,
    CitedEvidence,
    ContributingFactor,
    Detection,
    Evidence,
    FailureMode,
    FlagUndo,
    Hypothesis,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    IncidentStatus,
    Lessons,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    Report,
    ReportChannel,
    ResolutionStep,
    ReviewCriterion,
    RevisionSource,
    Standing,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Verdict,
    Weighing,
)
from argus_incidents.repository import events, hypotheses, incidents, postmortems, taken_actions
from argus_testkit import Assertion, Scenario, all_of
from argus_web.app import app
from fastapi.testclient import TestClient

from argus_web_test.framework.assertions import (
    POLLS_FOR_MORE,
    the_page_keeps_asking,
    the_page_links_to,
    the_page_says,
    the_page_shows,
    the_response_was,
)
from argus_web_test.framework.reading import attribute, page_at

# What htmx's "ask again in a moment" looks like in the rendered page. Named
# because two assertions read it and they must read the same thing: one saying
# the page polls and one saying it has stopped, disagreeing about the spelling,
# would both pass on a page that does neither.

# The postmortem's sections, by the names the page gives them, in the order the
# template puts them.
POSTMORTEM_SECTIONS = ["summary", "impact", "cause", "hypotheses", "trigger", "resolution",
                       "detection", "action-items", "lessons", "timeline", "leads",
                       "response-cost", "supporting", "review"]


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
            lambda: page_at("/history")
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
            lambda: page_at("/history")
        ) \
        .then(
            the_page_links_to(f"/incidents/{incident_id}")
        )


@pytest.mark.component
def test_the_history_keeps_asking_for_more() -> None:
    # The demo posture is somebody watching Argus's screen for it to react. A
    # history that only lists what existed when the page was opened means the
    # incident they are waiting for never arrives.
    Scenario() \
        .when(
            lambda: page_at("/history")
        ) \
        .then(
            the_page_keeps_asking()
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
            lambda: page_at("/history/list")
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
            lambda: [page_at("/history"), page_at(f"/incidents/{incident_id}")]
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_shows("subject", "first", "second")
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_shows("tested", "true", "false")
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says(a_cited_line)
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
        _an_attempt_taken_for(conn, incident_id, refuted, outcome=Verdict.REFUTED)
        _an_attempt_taken_for(conn, incident_id, confirmed, outcome=Verdict.CONFIRMED)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_shows("outcome", "refuted", "confirmed"),
            the_page_shows("undone", "true", "false")
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_keeps_asking()
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
            lambda: page_at(f"/incidents/{incident_id}")
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
            lambda: page_at(f"/incidents/{incident_id}/walk")
        ) \
        .then(
            the_page_shows("subject", "a-flag")
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
                the_response_was(HttpStatus.NOT_FOUND)
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
                assumptions=["dont care"]
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(a_root_cause)
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
                the_response_was(HttpStatus.OK)
            )


@pytest.mark.component
def test_the_postmortem_page_offers_the_document_as_a_pdf() -> None:
    # The same words in a file a reader keeps, forwards and attaches.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("postmortem-pdf", f"/incidents/{incident_id}/postmortem.pdf")
        )


@pytest.mark.component
def test_an_incident_with_no_postmortem_offers_no_pdf_of_one() -> None:
    # A download of nothing would be a file that fails to open.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_shows_no("postmortem-pdf")
        )


@pytest.mark.component
def test_the_postmortem_downloads_as_a_pdf_named_for_its_incident() -> None:
    # Saved among others like it, a file is found again by its name.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem.pdf")
            ) \
            .then(
                _a_pdf_to_save_as(f"argus-postmortem-{incident_id}.pdf")
            )


@pytest.mark.component
def test_an_incident_with_no_postmortem_has_no_pdf_of_one() -> None:
    # The page says so in words; a file has no words to say it with.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    with TestClient(app) as client:
        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{incident_id}/postmortem.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
            )


@pytest.mark.component
def test_an_unknown_incident_has_no_pdf() -> None:
    a_nonexistent_id = "00000000-0000-0000-0000-000000000000"

    with TestClient(app) as client:
        Scenario() \
            .given(
                a_nonexistent_id
            ) \
            .when(
                lambda: client.get(f"/incidents/{a_nonexistent_id}/postmortem.pdf")
            ) \
            .then(
                the_response_was(HttpStatus.NOT_FOUND)
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"/incidents/{incident_id}/withdraw"),
            the_page_shows("withdraw", incident_id)
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
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows_no("withdraw")
        )


@pytest.mark.component
def test_a_running_incident_can_be_resolved_from_its_page() -> None:
    # The other thing a person may tell Argus: that it is over. Offered beside
    # the withdraw button, because the two are the two ways a person ends an
    # incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_says(f"/incidents/{incident_id}/resolve"),
            the_page_shows("resolve", incident_id)
        ))


@pytest.mark.component
def test_an_incident_argus_escalated_can_still_be_resolved_and_not_withdrawn() -> None:
    # Argus stopped and somebody carried on - exactly the person who comes back
    # to report it over. Withdrawing it is another matter: there is nothing of
    # Argus's left running to stop.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.transition(conn, incident_id, IncidentStatus.ESCALATED)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            the_page_shows("resolve", incident_id),
            _the_page_shows_no("withdraw")
        ))


@pytest.mark.component
def test_a_withdrawn_incident_offers_no_way_to_resolve_it() -> None:
    # It ended for its own reason, and the answer to a press would be a 409
    # nobody had reason to expect.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            _the_page_shows_no("resolve")
        )


@pytest.mark.component
def test_the_postmortem_page_says_who_resolved_the_incident_and_what_they_said() -> None:
    # Beside the document rather than in it. A postmortem written before the
    # person reported the incident over is not rewritten, and one written after
    # is the model's prose - either way, who ended it, through which door, when
    # and in what words is read off the account and shown as it was recorded.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_person = "Kuki Buki"
    some_note = "rolled the flag back by hand"

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
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=["dont care"]
            )
        )
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=some_person, channel=ReportChannel.ARGUS_UI, note=some_note)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(some_person),
            the_page_says("the Argus UI"),
            the_page_says(some_note)
        ))


@pytest.mark.component
def test_an_incident_a_person_resolved_before_any_postmortem_says_who_on_its_page() -> None:
    # The document may never come - the walk can end without one - and the
    # person who ended the incident is owed the line either way.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_person = "Kuki Buki"
    some_note = "rolled the flag back by hand"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=some_person, channel=ReportChannel.ARGUS_UI, note=some_note)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("resolution", some_person),
            the_page_says(some_note)
        ))


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
                assumptions=["dont care"]
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(str(some_minutes)),
            the_page_says(str(some_responders)),
            the_page_says(some_title),
            the_page_says(some_other_title)
        ))


@pytest.mark.component
def test_the_postmortem_page_says_what_people_told_the_incident_and_what_it_changed() -> None:
    # The person who wrote a lead comes looking for what became of it. Their
    # words, what the investigation made of them and whether they changed what
    # was done are one answer, so the page gives all three together - and a
    # lead written too late to be weighed says so rather than standing bare.
    # Each is credited by name, and by the platform's id where it gave none.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_name = "Some Person"
    some_unnamed_person = "U-another-person"
    some_words = "the kuki flag was flipped at noon"
    some_reason = "the flag history agrees"
    some_effect = "it named the flag that was reverted"
    some_late_words = "it is the database again"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause="dont care",
                executive_summary="dont care",
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                leads=[
                    PostmortemLead(
                        label="L1",
                        person_id="U-some-person",
                        person_name=some_name,
                        text=some_words,
                        written_at=datetime(2026, 8, 30, 10, 41, tzinfo=UTC),
                        weighing=Weighing(standing=Standing.SUPPORTED, reason=some_reason),
                        effect=some_effect
                    ),
                    PostmortemLead(
                        label="L2",
                        person_id=some_unnamed_person,
                        person_name=None,
                        text=some_late_words,
                        written_at=datetime(2026, 8, 30, 10, 52, tzinfo=UTC),
                        weighing=None,
                        effect=None
                    )
                ]
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says(some_words),
            the_page_says(Standing.SUPPORTED.value),
            the_page_says(some_reason),
            the_page_says(some_effect),
            the_page_says(some_late_words),
            the_page_says("never weighed"),
            # Credited as the line credits them - by name, or by the id where
            # the platform gave no name - rather than found in an attribute.
            the_page_says(f"- {some_name},"),
            the_page_says(f"- {some_unnamed_person},")
        ))


@pytest.mark.component
def test_the_postmortem_page_shows_the_template_s_sections_in_its_order() -> None:
    # Google's order, the cause after what happened rather than before it: a
    # reader learns what broke and for how long before reading why.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[PostmortemLead(
            label="L1",
            person_id="U-some-person",
            person_name=None,
            text="dont care",
            written_at=datetime(2026, 8, 30, 10, 41, tzinfo=UTC),
            weighing=None,
            effect=None
        )])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("section", *POSTMORTEM_SECTIONS)
        )


@pytest.mark.component
def test_a_postmortem_section_with_nothing_in_it_is_still_shown_but_what_people_said() -> None:
    # A section left out reads as one nobody thought to write; one that says
    # it has nothing reads as the answer it is. What people told the incident
    # is the exception - an incident nobody wrote in has no such section.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("section", *[section for section in POSTMORTEM_SECTIONS
                                        if section != "leads"])
        )


@pytest.mark.component
def test_the_postmortem_header_names_its_incident_and_tells_its_two_times_apart() -> None:
    # When the service was broken and when the document was written are both
    # times, and a reader taking one for the other dates the incident wrong.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("postmortem-of", incident_id),
            the_page_shows("time", "incident", "written")
        ))


@pytest.mark.component
def test_the_postmortem_header_links_its_incident_in_full() -> None:
    # The id alone names the incident and leads nowhere; in full for the reason
    # the supporting links are - the document is read away from this screen.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("incident-link", f"http://testserver/incidents/{incident_id}")
        )


@pytest.mark.component
def test_the_postmortem_header_answers_its_five_questions_in_order() -> None:
    # What a reader asks before reading any of it: which incident, when, how
    # finished the document is, who wrote it, and who ended the incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("head", "incident", "date", "status", "written-by", "ended-by")
        )


@pytest.mark.component
def test_the_postmortem_header_dates_the_incident_once_on_both_clocks() -> None:
    # The date said once and the window's ends as times of that day. Each end
    # is also carried whole, so the reader's own clock can say it in their zone.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_onset = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(timeline=[
            TimelineEntry(at=some_onset, who=None, text="dont care",
                          marker=TimelineMarker.IMPACT_BEGINS),
            TimelineEntry(at=some_onset + timedelta(minutes=9), who=None, text="dont care",
                          marker=TimelineMarker.IMPACT_ENDS)
        ]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("Oct 11, 2026, 14:03 to 14:12 UTC"),
            the_page_shows("local-from", "2026-10-11T14:03:00Z"),
            the_page_shows("local-to", "2026-10-11T14:12:00Z")
        ))


@pytest.mark.component
def test_the_postmortem_header_counts_the_action_items_already_done() -> None:
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(action_items=[
            ActionItem(number="AI-1", text="dont care", type=ActionItemType.MITIGATE,
                       owner=None, tracking=None, status=ActionItemStatus.DONE),
            ActionItem(number="AI-2", text="dont care", type=ActionItemType.PREVENT,
                       owner=None, tracking=None, status=ActionItemStatus.OPEN)
        ]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("Draft. 1 of 2 action items are done.")
        )


@pytest.mark.component
@pytest.mark.parametrize(("met", "said"), [(None, "Not reviewed yet."), (True, "Reviewed.")])
def test_the_postmortem_header_says_whether_a_person_has_reviewed_it(met: bool | None,
                                                                     said: str) -> None:
    # A box only a person can tick, left unticked, is a document nobody who
    # could disagree with it has read yet.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(review=[
            ReviewCriterion(criterion="dont care", met=True),
            ReviewCriterion(criterion="dont care either", met=met)
        ]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("Argus Postmortem agent"),
            the_page_says(said)
        ))


@pytest.mark.component
def test_the_postmortem_header_says_argus_ended_an_incident_nobody_reported_over() -> None:
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(resolution=[
            ResolutionStep(at=datetime(2026, 10, 11, 14, 11, tzinfo=UTC),
                           action="revert-feature-flag on monthly-spend-feature",
                           by="Argus", reversible=True, outcome="confirmed, still in place",
                           label="M1")
        ]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("ended-by", "Argus")
        )


@pytest.mark.component
def test_the_postmortem_header_says_the_person_who_reported_the_incident_over_ended_it() -> None:
    # The person's word over the document's: a write-up composed before the
    # report is not rewritten, so who ended it is read off the account.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_person = "Kuki Buki"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])
        events.record(conn, StatusChanged(
            incident_id=incident_id,
            to_status=IncidentStatus.RESOLVED,
            reported=Report(by=some_person, channel=ReportChannel.ARGUS_UI, note=None)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("ended-by", some_person)
        )


@pytest.mark.component
def test_the_postmortem_title_says_the_symptom_and_the_change_it_began_with() -> None:
    # The symptom in the model's words and the change in the record's: what a
    # reader looking for this incident again remembers it by.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(
            symptom="Account pages failed",
            trigger=Trigger(subject="monthly-spend-feature", from_state="off", to_state="on",
                            changed_at=None)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", "Account pages failed while monthly-spend-feature was on")
        )


@pytest.mark.component
def test_a_postmortem_that_names_no_symptom_is_titled_by_its_alert() -> None:
    # A document written before the model was asked for one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        _a_postmortem_recorded_for(conn, incident_id, leads=[])

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", "HighErrorRate on io-shop")
        )


@pytest.mark.component
def test_the_trigger_says_what_kind_of_change_it_was_and_between_which_states() -> None:
    # A name alone reads as anything. Said as a flag, its two states are the
    # ones it moved between - the one it left, and the one it went to.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject="monthly-spend-feature", from_state="off", to_state="on",
            changed_at=None, kind=ChangeKind.FLAG_TOGGLE
        )))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says("flag went from"),
            the_page_shows("from-state", "off"),
            the_page_shows("to-state", "on")
        ))


@pytest.mark.component
def test_a_deployment_trigger_says_which_service_went_between_which_revisions() -> None:
    # A deployment's subject is the service, and its two states are revisions.
    # Said the way a flag is said, the new revision stood where the service
    # goes, and both were shouted in capitals as though they were ON and OFF.
    some_alert = Alert(service="io-shop", alert_name="SpendTotalsDoNotReconcile")
    old_revision = "4c810f22894e612ced87f5ee3f3062dfeb785050"
    new_revision = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject=new_revision, from_state=old_revision, to_state=new_revision,
            changed_at=None, kind=ChangeKind.DEPLOY
        )))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads("io-shop was deployed from 4c810f2 to 26f1d7e")
        )


@pytest.mark.component
def test_a_deployment_trigger_names_the_service_and_its_revision_in_the_title() -> None:
    # A flag's "while X was Y" said of a deployment is the revision twice over.
    some_alert = Alert(service="io-shop", alert_name="SpendTotalsDoNotReconcile")
    symptom = "Stored spend totals were wrong"
    new_revision = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(
            symptom=symptom,
            trigger=Trigger(subject=new_revision,
                            from_state="4c810f22894e612ced87f5ee3f3062dfeb785050",
                            to_state=new_revision, changed_at=None,
                            kind=ChangeKind.DEPLOY)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_shows("title", f"{symptom} while io-shop ran 26f1d7e"),
            _the_page_reads(f"{symptom} while io-shop ran 26f1d7e")
        ))


@pytest.mark.component
def test_the_impact_says_how_many_requests_failed() -> None:
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "impact": Impact(duration=timedelta(minutes=9), extent=ImpactExtent.MEASURED,
                             peak_error_rate=0.338, requests_failed=4210)
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("4,210")
        )


@pytest.mark.component
def test_the_trigger_says_who_made_the_change() -> None:
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject="monthly-spend-feature", from_state="off", to_state="on",
            changed_at=None, kind=ChangeKind.FLAG_TOGGLE, actor="kuki"
        )))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("by kuki")
        )


@pytest.mark.component
def test_a_suspected_trigger_is_said_as_suspected() -> None:
    # Nothing tested it. Shown as the trigger plainly, it would read as the
    # cause established - which is the one thing the document cannot say.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(trigger=Trigger(
            subject="monthly-spend-feature", from_state="off", to_state="on",
            changed_at=None, suspected=True
        )))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("trigger", "suspected")
        )


@pytest.mark.component
def test_a_suspected_trigger_stays_out_of_the_title() -> None:
    # The title is the one line read by everybody who reads nothing else, and
    # "while the flag was on" there says the flag did it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_symptom = "Account pages failed"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(
            symptom=some_symptom,
            trigger=Trigger(subject="monthly-spend-feature", from_state="off",
                            to_state="on", changed_at=None, suspected=True)
        ))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("title", some_symptom)
        )


@pytest.mark.component
@pytest.mark.parametrize(("extent", "said"), [
    (ImpactExtent.MEASURED, "measured"),
    (ImpactExtent.AT_LEAST, "a lower bound"),
    (ImpactExtent.UNOBSERVED, "a lower bound")
])
def test_a_loss_over_an_incident_that_never_ended_is_said_to_be_at_least(
        extent: ImpactExtent, said: str) -> None:
    # Takings counted up to where the metrics stopped, of an incident still
    # going there: what it cost is that much or more, and a figure with no
    # "at least" reads as the whole of it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "customer_loss_estimate": Decimal("500"),
            "estimate_currency": "usd",
            "impact": Impact(duration=timedelta(hours=2), extent=extent, peak_error_rate=None)
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("loss-is", said)
        )


@pytest.mark.component
@pytest.mark.parametrize(("extent", "read"), [
    (ImpactExtent.MEASURED, "none"),
    (ImpactExtent.AT_LEAST, "none so far"),
    (ImpactExtent.UNOBSERVED, "none so far")
])
def test_no_loss_is_said_as_none_rather_than_as_an_amount(extent: ImpactExtent,
                                                          read: str) -> None:
    # "At least 0.00 USD" is true and reads as a figure somebody forgot to
    # fill in. Said as none, it is a finding - and "so far" keeps what the
    # "at least" was there to say, of an incident still going when the
    # takings were counted.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "customer_loss_estimate": Decimal("0"),
            "estimate_currency": "usd",
            "impact": Impact(duration=timedelta(hours=2), extent=extent, peak_error_rate=None)
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"{read} customer loss (estimated)")
        )


@pytest.mark.component
def test_the_postmortem_page_shows_every_amount_to_the_cent() -> None:
    # Stored as computed, rounded only for show: twenty-six decimal places of
    # a loss estimate claim a precision nobody measured.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=Decimal("1736.68485900091116011163646"),
                estimate_currency="usd",
                engineer_minutes=22,
                responders=1,
                responder_cost_estimate=Decimal("412.5"),
                responder_cost_currency="usd",
                tokens_spent=None,
                assumptions=[]
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("1,736.68 USD")
        )


@pytest.mark.component
def test_detection_names_the_alert_the_way_the_header_does() -> None:
    # One name for one alert across the page: the header says the alert, so
    # Detection does too, rather than the rule's own identifier beside it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_onset = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "detection": Detection(alerted_at=some_onset + timedelta(minutes=2),
                                   rule="io-shop-high-error-rate",
                                   onset_at=some_onset,
                                   gap=timedelta(minutes=2))
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("HighErrorRate fired at")
        )


@pytest.mark.component
def test_the_postmortem_page_says_how_long_the_alert_took_in_minutes_and_seconds() -> None:
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_onset = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                detection=Detection(alerted_at=some_onset + timedelta(minutes=2, seconds=40),
                                    rule="HighErrorRate",
                                    onset_at=some_onset,
                                    gap=timedelta(minutes=2, seconds=40))
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says("2m 40s")
        )


@pytest.mark.component
def test_the_resolution_names_the_fix_proposed_as_well_as_the_action_taken() -> None:
    # The mitigation ended the symptom; the fix is what ends the cause. Left
    # out of the resolution, the document reads as finished while the one
    # thing still owed sits in a list further down.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_fix = "https://github.invalid/ohadraz/io-shop/pull/7"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "pull_request": OpenedPullRequest(number=7, url=some_fix, branch="argus/fix-abc")
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("resolution-fix", some_fix)
        )


@pytest.mark.component
def test_the_postmortem_page_links_its_walk_and_the_fix_in_full_and_not_itself() -> None:
    # In full, because the document is read away from the screen it came from -
    # sent onwards, printed - where an address relative to nothing leads
    # nowhere. Not itself: a page linking to the page it is is a link nobody
    # follows. The test client serves the app at its own default host.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_fix = "https://github.invalid/ohadraz/io-shop/pull/7"

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(
            conn,
            incident_id,
            PostmortemDocument(
                root_cause=None,
                executive_summary=None,
                customer_loss_estimate=None,
                estimate_currency=None,
                engineer_minutes=None,
                responders=None,
                tokens_spent=None,
                assumptions=[],
                pull_request=OpenedPullRequest(number=7, url=some_fix, branch="argus/fix-abc")
            )
        )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_shows("link",
                           f"http://testserver/incidents/{incident_id}",
                           some_fix)
        )


@pytest.mark.component
def test_every_row_the_prose_can_cite_answers_to_its_label() -> None:
    # The prose cites hypotheses, actions, action items, lines of the
    # narration, changes and log messages read, and leads by label, and a link
    # to one has to land on its row. A marker was never shown to the model, so
    # nothing cites it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    dont_care_moment = datetime(2026, 10, 11, 14, 11, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(
            timeline=[
                TimelineEntry(at=dont_care_moment, who=None, text="dont care",
                              marker=TimelineMarker.DETECTED),
                TimelineEntry(at=dont_care_moment, who="Investigator", text="dont care",
                              label="T1")
            ],
            action_items=[
                ActionItem(number="AI-1", text="dont care", type=ActionItemType.MITIGATE,
                           owner=None, tracking=None, status=ActionItemStatus.DONE)
            ],
            resolution=[
                ResolutionStep(at=dont_care_moment, action="dont care", by="Argus",
                               reversible=True, outcome="dont care", label="M1")
            ]
        ).model_copy(update={
            "hypotheses": [HypothesisConsidered(summary="dont care", confidence=None,
                                                result="dont care", label="C1")],
            "changes_read": [_a_change_read("P1")],
            "log_messages_read": [CitedEvidence(label="G3fa2", text="dont care")],
            "leads": [PostmortemLead(label="L1", person_id="U-some-person", person_name=None,
                                     text="dont care", written_at=dont_care_moment,
                                     weighing=None, effect=None)]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says('id="C1"'),
            the_page_says('id="M1"'),
            the_page_says('id="AI-1"'),
            the_page_says('id="T1"'),
            the_page_says('id="P1"'),
            the_page_says('id="G3fa2"'),
            the_page_says('id="L1"')
        ))


@pytest.mark.component
def test_what_the_alert_said_answers_to_its_label() -> None:
    # The chain's symptom rests on it, and a citation of it has to land.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "detection": Detection(alerted_at=datetime(2026, 10, 11, 14, 11, tzinfo=UTC),
                                   rule="dont care", onset_at=None, gap=None,
                                   said=CitedEvidence(label="AL1", text="240 totals are off"))
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says('id="AL1"'),
            the_page_says("240 totals are off")
        ))


@pytest.mark.component
@pytest.mark.parametrize("prose", [
    pytest.param({"executive_summary": "C1 was right."}, id="summary"),
    pytest.param({"root_cause": "C1 was right."}, id="root_cause"),
    pytest.param({"causal_chain": [ChainStep(text="C1 was right.", cites=[])]},
                 id="causal_chain"),
    pytest.param({"causal_chain": [ChainStep(text="dont care",
                                             cites=[CitedEvidence(label="C1",
                                                                  text="dont care")])]},
                 id="causal_chain_evidence"),
    pytest.param({"contributing_factors": [ContributingFactor(text="C1 was right.",
                                                              addressed_by=[])]},
                 id="contributing_factor"),
    pytest.param({"action_items": [ActionItem(number="AI-1", text="Keep C1 from coming back.",
                                              type=ActionItemType.PREVENT, owner=None,
                                              tracking=None, status=ActionItemStatus.OPEN)]},
                 id="action_item"),
    pytest.param({"recommended_action": "Undo what C1 named."}, id="recommended_action"),
    pytest.param({"lessons": Lessons(went_well=["C1 was right."])}, id="lessons"),
    pytest.param({"leads": [PostmortemLead(label="L1", person_id="U-some-person",
                                           person_name=None, text="dont care",
                                           written_at=datetime(2026, 10, 11, 14, 11, tzinfo=UTC),
                                           weighing=None, effect="It named what C1 blamed.")]},
                 id="lead_effect"),
    pytest.param({"assumptions": ["C1 was taken at its word."]}, id="assumptions")
])
def test_a_label_cited_in_any_prose_links_to_its_row(prose: dict[str, object]) -> None:
    # Wherever the model writes, it may cite a row by its label, and a reader
    # following the citation is taken to the row rather than left to find it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary="dont care", confidence=None,
                                                result="dont care", label="C1")],
            **prose
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_links_to("#C1")
        )


@pytest.mark.component
def test_a_row_standing_for_several_candidates_answers_to_each_label() -> None:
    # A link to either candidate lands on the one row, which is labelled with
    # both.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary="dont care", confidence=None,
                                                result="dont care", label="C1", also=["C2"])]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_says('id="C1"'),
            the_page_says('id="C2"'),
            the_page_says('<td class="label">C1, C2</td>')
        ))


@pytest.mark.component
def test_a_candidate_a_line_of_the_timeline_names_links_to_its_row() -> None:
    # The line that formed the candidates names them by label, and a reader
    # follows each to what it was.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(summary="dont care", confidence=None,
                                                result="dont care", label="C1")],
            "timeline": [TimelineEntry(at=datetime(2026, 10, 11, 14, 3, tzinfo=UTC),
                                       who="Investigator Agent",
                                       text="Formed 1 candidate cause, best first: C1",
                                       label="T1")]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says('best first: <a href="#C1">C1</a>')
        )


@pytest.mark.component
def test_a_change_the_root_cause_names_links_to_its_row() -> None:
    # "The deploy P2" means nothing to a reader until it leads somewhere: to
    # the change, said as the model was shown it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": "The deploy P2 switched the model.",
            "changes_read": [_a_change_read("P2")]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to("#P2"),
            the_page_says('id="P2"')
        ))


@pytest.mark.component
def test_what_a_deployment_changed_the_root_cause_names_links_to_its_row() -> None:
    # "As D1 shows" leads to the diff, every line of it as the model read it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": "As D1 shows, the categoriser's model went from v1 to v2.",
            "deployment_changes_read": [CitedEvidence(
                label="D1",
                text="modified deploy/values-production.yaml\n  -  model: v1\n  +  model: v2")]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to("#D1"),
            the_page_says('id="D1"'),
            the_page_says("  -  model: v1")
        ))


@pytest.mark.component
def test_what_code_fix_read_the_root_cause_names_links_to_its_row() -> None:
    # "As F1 reads the code" leads to the reading, said as one nothing ran.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": "As F1 reads the code, v2 meets input it was not built for.",
            "code_read": [CitedEvidence(label="F1", text="the categoriser does not lowercase")]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to("#F1"),
            the_page_says('id="F1"'),
            the_page_says("nothing ran it")
        ))


@pytest.mark.component
def test_a_change_read_links_out_to_its_commit_its_repository_and_its_directory() -> None:
    # The row says where the change came from, and a reader opens it there.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "changes_read": [CitedChange(
                label="P1",
                change=ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    occurred_at="2026-10-11T14:00:00Z",
                    reference=some_revision,
                    summary=(f"deployed revision {some_revision} from the acme/shop "
                             f"repository's deploy/ directory"),
                    revision_source=RevisionSource(
                        repository="acme/shop",
                        repository_address=some_repository,
                        revision_address=f"{some_repository}/commit/{some_revision}",
                        directory="deploy",
                        directory_address=f"{some_repository}/tree/{some_revision}/deploy")),
                short_reference=some_revision[:7])]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            the_page_links_to(f"{some_repository}/commit/{some_revision}"),
            the_page_links_to(some_repository),
            the_page_links_to(f"{some_repository}/tree/{some_revision}/deploy")
        ))


@pytest.mark.component
def test_a_deployment_trigger_s_revision_opens_its_commit() -> None:
    # The trigger names the revision deployed as its row does, and a reader
    # opens it from the sentence that says what set the incident off.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    commit = f"{some_repository}/commit/{some_revision}"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "trigger": Trigger(subject="dont care",
                               from_state="4c810f2aa1e9a6f3b7c9d0e1f2a3b4c5d6e7f809",
                               to_state=some_revision,
                               changed_at=None,
                               kind=ChangeKind.DEPLOY),
            "changes_read": [CitedChange(
                label="P1",
                change=ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    occurred_at="2026-10-11T14:00:00Z",
                    reference=some_revision,
                    summary="dont care",
                    revision_source=RevisionSource(
                        repository="acme/shop",
                        repository_address=some_repository,
                        revision_address=commit)),
                short_reference=some_revision[:7])]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'data-to-state="{some_revision[:7]}"><a href="{commit}"')
        )


@pytest.mark.component
def test_a_revision_the_root_cause_names_opens_its_commit() -> None:
    # The prose names the deploy by its revision, and a reader opens it from
    # there - not only from the row listing the change, which links it too.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    commit = f"{some_repository}/commit/{some_revision}"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "root_cause": f"The deploy of revision {some_revision[:7]} broke it.",
            "changes_read": [CitedChange(
                label="P1",
                change=ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    occurred_at="2026-10-11T14:00:00Z",
                    reference=some_revision,
                    summary="dont care",
                    revision_source=RevisionSource(
                        repository="acme/shop",
                        repository_address=some_repository,
                        revision_address=commit)),
                short_reference=some_revision[:7])]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{some_revision[:7]}</a> broke it.')
        )


@pytest.mark.component
def test_a_revision_a_hypothesis_names_opens_its_commit() -> None:
    # The candidate wrote it whole; the row says it short, as the trigger and
    # the timeline beside it do, and a reader opens it from there.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    commit = f"{some_repository}/commit/{some_revision}"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with().model_copy(update={
            "hypotheses": [HypothesisConsidered(
                summary=f"{some_revision} made every page slow", confidence=0.8,
                result="confirmed", label="C1")],
            "changes_read": [CitedChange(
                label="P1",
                change=ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    occurred_at="2026-10-11T14:00:00Z",
                    reference=some_revision,
                    summary="dont care",
                    revision_source=RevisionSource(
                        repository="acme/shop",
                        repository_address=some_repository,
                        revision_address=commit)),
                short_reference=some_revision[:7])]
        }))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{some_revision[:7]}</a> made every page slow')
        )


@pytest.mark.component
def test_a_revision_the_walk_names_opens_its_commit_from_the_incident_page() -> None:
    # Said short as the postmortem says it, and so a name a reader cannot look
    # up by hand.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    commit = f"{some_repository}/commit/{some_revision}"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        events.record(conn, _a_deploy_read_on(incident_id, some_revision, some_repository))
        events.record(conn, CandidateSelected(incident_id=incident_id, hypothesis_id=new_id(),
                                              summary=f"[{some_revision}] made every page slow",
                                              confidence=None))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(
            the_page_says(f'<a href="{commit}" target="_blank" rel="noopener noreferrer">'
                          f'{some_revision[:7]}</a> made every page slow')
        )


@pytest.mark.component
def test_a_change_read_is_named_on_the_incident_page_as_its_postmortem_row_names_it() -> None:
    # Short, and opening where it was committed; what it did in the same words,
    # its revision and repository each opening where they are.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "https://github.com/acme/shop"
    commit = f"{some_repository}/commit/{some_revision}"
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        events.record(conn, _a_deploy_read_on(
            incident_id, some_revision, some_repository,
            summary=f"deployed revision {some_revision} from the acme/shop repository"))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}")
        ) \
        .then(all_of(
            _the_page_does_not_read(f"<code>{some_revision}</code>"),
            the_page_says(f'deployed revision <a href="{commit}" target="_blank" '
                          f'rel="noopener noreferrer">{some_revision[:7]}</a> from the '),
            the_page_links_to(some_repository)
        ))


@pytest.mark.component
def test_a_contributing_factor_links_to_the_action_items_that_answer_it() -> None:
    # The items are named, not written out, so the name is the only way from
    # the condition to what is being done about it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(action_items=[
            ActionItem(number="AI-1", text="dont care", type=ActionItemType.PREVENT,
                       owner=None, tracking=None, status=ActionItemStatus.OPEN)
        ]).model_copy(update={"contributing_factors": [
            ContributingFactor(text="dont care", addressed_by=["AI-1"])
        ]}))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            the_page_links_to("#AI-1")
        )


@pytest.mark.component
def test_a_timeline_row_on_a_new_day_says_its_date() -> None:
    # A time of day alone reads in order only within one day: an onset a week
    # before the alert, said as 16:10 above 16:08, reads as time running
    # backwards. The date is said where the day changes, and only there.
    some_alert = Alert(service="io-shop", alert_name="SpendTotalsDoNotReconcile")
    onset = datetime(2026, 9, 28, 16, 10, tzinfo=UTC)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        postmortems.record(conn, incident_id, _a_document_with(timeline=[
            TimelineEntry(at=onset, who=None, text="the incident began"),
            TimelineEntry(at=onset + timedelta(hours=1), who=None, text="it went on"),
            TimelineEntry(at=datetime(2026, 10, 5, 16, 8, 38, tzinfo=UTC), who=None,
                          text="it was found")
        ]))

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(all_of(
            _the_page_reads("Sep 28 16:10:00 the incident began"),
            _the_page_reads("17:10:00 it went on"),
            _the_page_does_not_read("Sep 28 17:10:00"),
            _the_page_reads("Oct 05 16:08:38 it was found")
        ))


@pytest.mark.component
def test_the_impact_says_what_the_alert_found() -> None:
    # Where the damage is not a rate - totals written wrong rather than requests
    # failed - the cards read "not measured" and "not counted", and the one
    # measurement there is sits in the alert. Left there, the impact section
    # reads as an incident that did nothing.
    finding = "240 of 240 stored totals are wrong; the widest is 1,297.31 short"
    an_alert_with_a_finding = Alert(service="io-shop", alert_name="SpendTotalsDoNotReconcile",
                                    summary=finding, claim=AlarmClaim.ITS_OWN_FINDING)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, an_alert_with_a_finding)
        postmortems.record(conn, incident_id, _a_document_with())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_reads(f"customer loss (estimated) What the alert found: {finding}")
        )


@pytest.mark.component
def test_an_alert_that_found_nothing_in_words_adds_nothing_to_the_impact() -> None:
    an_alert_with_no_finding = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, an_alert_with_no_finding)
        postmortems.record(conn, incident_id, _a_document_with())

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: page_at(f"/incidents/{incident_id}/postmortem")
        ) \
        .then(
            _the_page_does_not_read("What the alert found")
        )


def _a_postmortem_recorded_for(conn: psycopg.Connection,
                               incident_id: str,
                               leads: list[PostmortemLead]) -> None:
    """A document with nothing in any section but the leads it is given."""
    postmortems.record(
        conn,
        incident_id,
        PostmortemDocument(
            root_cause=None,
            executive_summary=None,
            customer_loss_estimate=None,
            estimate_currency=None,
            engineer_minutes=None,
            responders=None,
            tokens_spent=None,
            assumptions=[],
            leads=leads
        )
    )


def _the_page_reads(text: str) -> Assertion[str]:
    """What a reader sees, markup and line breaks aside.

    Read off the text rather than the markup, because a value can sit in an
    attribute in one spelling and on the page in another - and the reader only
    ever sees the second.
    """
    def assertion(page: str) -> bool:
        read = " ".join(re.sub(r"<[^>]+>", " ", page).split())

        if text not in read:
            raise AssertionError(f"Expected the page to read [{text}], it did not.")

        return True

    return assertion


def _the_page_does_not_read(text: str) -> Assertion[str]:
    """What a reader must not see, markup and line breaks aside."""
    def assertion(page: str) -> bool:
        read = " ".join(re.sub(r"<[^>]+>", " ", page).split())

        if text in read:
            raise AssertionError(f"Expected the page not to read [{text}], it did.")

        return True

    return assertion


def _a_document_with(timeline: list[TimelineEntry] | None = None,
                     action_items: list[ActionItem] | None = None,
                     review: list[ReviewCriterion] | None = None,
                     resolution: list[ResolutionStep] | None = None,
                     symptom: str | None = None,
                     trigger: Trigger | None = None) -> PostmortemDocument:
    """A document with nothing in any section but the ones it is given."""
    return PostmortemDocument(
        root_cause=None,
        executive_summary=None,
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=None,
        responders=None,
        tokens_spent=None,
        assumptions=[],
        timeline=timeline or [],
        action_items=action_items or [],
        review=review or [],
        resolution=resolution or [],
        symptom=symptom,
        trigger=trigger
    )


def _a_change_read(label: str) -> CitedChange:
    """A flag toggled, read under `label`."""
    return CitedChange(label=label,
                       change=ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                          occurred_at="2026-10-11T14:00:00Z",
                                          reference="dont-care",
                                          summary="dont care"),
                       short_reference="dont-care")


def _a_pdf_to_save_as(filename: str) -> Assertion[httpx2.Response]:
    """A PDF, handed over as a file to save under `filename` rather than shown
    in the browser's tab."""
    def assertion(response: httpx2.Response) -> bool:
        got = (response.status_code, response.headers.get("content-type"),
               response.headers.get("content-disposition"), response.content[:5])
        expected = (HttpStatus.OK, "application/pdf", f'attachment; filename="{filename}"',
                    b"%PDF-")

        if got != expected:
            raise AssertionError(f"Expected the status, type, disposition and first bytes "
                                 f"{expected}, got {got}.")

        return True

    return assertion


def _the_page_shows_no(name: str) -> Assertion[str]:
    """That one `data-` attribute is absent altogether.

    Its own assertion rather than an empty `the_page_shows`, because "shows
    nothing" is the claim being made, and a call with no values to show reads
    as one somebody forgot to finish.
    """
    def assertion(page: str) -> bool:
        shown = attribute(name, page)

        if shown:
            raise AssertionError(f"Expected no [{name}] at all, got {shown}.")

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
        listed = attribute("incident", page)

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
        listed = attribute("incident", page)

        if incident_id not in listed:
            raise AssertionError(f"Expected [{incident_id}] to be listed, got {listed}.")

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


def _the_page_has_stopped_asking() -> Assertion[str]:
    def assertion(page: str) -> bool:
        if POLLS_FOR_MORE in page:
            raise AssertionError("Expected the page to have stopped asking, it had not.")

        return True

    return assertion


def _a_deploy_read_on(incident_id: str,
                      revision: str,
                      repository: str,
                      summary: str = "dont care") -> ChangesRetrieved:
    """A deploy of `revision` read, which can be opened where `repository` is."""
    return ChangesRetrieved(
        incident_id=incident_id,
        window_start="2026-10-11T13:55:00Z",
        window_end="2026-10-11T14:05:00Z",
        changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                             occurred_at="2026-10-11T14:00:00Z",
                             reference=revision,
                             summary=summary,
                             revision_source=RevisionSource(
                                 repository="acme/shop",
                                 repository_address=repository,
                                 revision_address=f"{repository}/commit/{revision}"))])


def _a_candidate_recorded_for(conn: psycopg.Connection,
                              incident_id: str,
                              subject: str,
                              rank: int,
                              evidence: list[str] | None = None) -> str:
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary=f"dont care - {subject}",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
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
                          outcome: Verdict) -> None:
    taken_actions.record(
        conn,
        incident_id,
        hypothesis_id=hypothesis_id,
        action_type="revert-feature-flag",
        subject="dont-care",
        outcome=outcome,
        undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True)
    )
