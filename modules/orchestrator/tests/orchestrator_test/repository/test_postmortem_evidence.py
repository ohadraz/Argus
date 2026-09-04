from __future__ import annotations

from datetime import datetime

import psycopg
import pytest
from agent_postmortem import IncidentEvidence
from argus_core.events import LogsRetrieved, OnsetDetected
from argus_core.ids import new_id
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_core.timestamps import parse_iso
from argus_testkit import Assertion, Scenario, all_of
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import attempting
from orchestrator.postmortem import gather_evidence
from orchestrator.repository import events, hypotheses, incidents

"""Turning four tables back into one incident.

The agent holds no connection and reads no rows: what it is handed is this,
assembled from the incident's own row, the account it published, the
candidates it ranked and the actions it took. Gathering is the Orchestrator's
work because the tables are, and because an agent that queried for its own
evidence could ask a different question than the page beside it.

Nothing here is derived or judged. Every line comes from something that was
recorded while it was happening - which is the point: what happened was
decided then, and a postmortem re-deciding it from conclusions would be
writing a different incident.
"""

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"


@pytest.mark.integration
def test_the_evidence_spans_the_incident_from_its_start_to_its_end() -> None:
    # The window every figure in the document is measured over. Taken from the
    # incident's own row rather than from the last thing logged, so it does not
    # move when something is written late.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _spans_the_incident(conn, incident_id)
            )


@pytest.mark.integration
def test_the_evidence_carries_the_candidates_the_investigation_ranked() -> None:
    # Including the ones never tried. An investigation that was confident and
    # right and one that ran out of options look identical from their outcome,
    # and the difference is most of what the walk has to say.
    some_cause = "the checkout fallback flag was switched off"
    some_cause_type = CauseType.FEATURE_FLAG_TOGGLE
    dont_care_confidence = 0.8

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                lambda: hypotheses.record(conn, Hypothesis(
                    incident_id=incident_id,
                    summary=some_cause,
                    cause_type=some_cause_type,
                    confidence=dont_care_confidence,
                    supporting_evidence=[]
                ))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: evidence.candidates, some_cause)
            )


@pytest.mark.integration
def test_the_evidence_carries_the_log_lines_the_incident_read() -> None:
    # From the published account rather than from the log store, which has
    # moved on. What the model explains has to be what Argus actually saw.
    some_window_start = "2026-09-02T11:30:00Z"
    some_window_end = "2026-09-02T12:30:00Z"
    some_log_line = "12:04 ERROR checkout: fallback unavailable"

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start=some_window_start,
                    window_end=some_window_end,
                    lines=[some_log_line]
                ))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: evidence.log_lines, some_log_line)
            )


@pytest.mark.integration
def test_the_evidence_carries_the_timeline_in_the_order_it_happened() -> None:
    # The narration the document is written from. Out of order it is a
    # different incident: a mitigation before the investigation that proposed
    # it explains nothing.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _timeline_begins_with(IncidentStatus.INVESTIGATING)
            )


@pytest.mark.integration
def test_an_incident_that_has_not_ended_cannot_be_summarised() -> None:
    # A postmortem is written once, when the incident is over. Asked for one
    # earlier, this refuses rather than inventing an end - a duration measured
    # to "now" would be a different number every time it was asked for.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(
                    conn, Alert(service="io-shop", alert_name="HighErrorRate"))
            ) \
            .when(
                attempting(lambda: gather_evidence(conn, incident_id))
            ) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.integration
def test_an_incident_that_does_not_exist_cannot_be_summarised() -> None:
    # Distinct from an incident still running: there is nothing to summarise
    # rather than nothing yet. Both refuse, and neither invents a document.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .when(
                attempting(lambda: gather_evidence(conn, new_id()))
            ) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.integration
def test_the_evidence_carries_the_onset_the_investigation_measured() -> None:
    # The instant the service actually began to fail, which is not the instant
    # Argus was told: an alert fires on a rule that needs some minutes of bad
    # traffic to trip. The loss is measured from the onset, so those minutes
    # are the difference between a baseline of calm trade and one that already
    # contains the damage.
    #
    # Read from what the Investigator published rather than measured again
    # here. A postmortem that re-derived it from a wider window would date the
    # same incident differently from the page that showed it.
    some_onset = "2026-09-02T11:50"

    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn, incident_id, OnsetDetected(incident_id=incident_id,
                                                     onset=some_onset))
            ) \
            .then(
                _carries_the_onset(parse_iso(some_onset))
            )


@pytest.mark.integration
def test_an_incident_whose_onset_was_never_found_carries_none() -> None:
    # A window in which no minute departed from the baseline has no onset to
    # anchor on (spec §9), so the investigation exits without publishing one.
    # The gathering must report that rather than substituting the alert's own
    # time, because the document refuses to cost an incident it cannot date.
    with psycopg.connect(DATABASE_URL) as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_no_onset()
            )


def _the_evidence_after_publishing(conn: psycopg.Connection,
                                   incident_id: str,
                                   event: OnsetDetected) -> IncidentEvidence:
    events.record(conn, event)

    return gather_evidence(conn, incident_id)


def _carries_the_onset(expected: datetime) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.onset_at != expected:
            raise AssertionError(
                f"Expected the onset [{expected}], got [{evidence.onset_at}].")

        return True

    return assertion


def _carries_no_onset() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.onset_at is not None:
            raise AssertionError(
                f"Expected no onset where none was published, got "
                f"[{evidence.onset_at}] - the alert's own time would date the "
                f"loss from after the damage began.")

        return True

    return assertion


def _an_incident_that_ended(conn: psycopg.Connection) -> str:
    incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
        actor=Actor.MITIGATION,
        action="dont care",
    )

    return incident_id


def _spans_the_incident(conn: psycopg.Connection,
                        incident_id: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        incident = incidents.get(conn, incident_id)
        assert incident is not None and incident.ended_at is not None

        return all_of(
            _starts_at(incident.created_at),
            _ends_at(incident.ended_at)
        )(evidence)

    return assertion


def _starts_at(expected: object) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.started_at != expected:
            raise AssertionError(
                f"expected the evidence to start at [{expected}], got [{evidence.started_at}]")

        return True

    return assertion


def _ends_at(expected: object) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.ended_at != expected:
            raise AssertionError(
                f"expected the evidence to end at [{expected}], got [{evidence.ended_at}]")

        return True

    return assertion


def _mentions_among(reading: object, expected: str) -> Assertion[IncidentEvidence]:
    """One line of the bundle, whichever list it belongs in.

    The lists differ in what they hold and not in how they are checked, so the
    test names the list and the line and nothing else.
    """
    def assertion(evidence: IncidentEvidence) -> bool:
        lines = reading(evidence)  # type: ignore[operator]

        if not any(expected in line for line in lines):
            raise AssertionError(f"expected [{expected}] among {lines}")

        return True

    return assertion


def _timeline_begins_with(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if not evidence.timeline or expected not in evidence.timeline[0]:
            raise AssertionError(
                f"expected the timeline to open on [{expected}], got {evidence.timeline}")

        return True

    return assertion
