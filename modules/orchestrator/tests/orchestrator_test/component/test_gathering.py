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

The last case covers the other half of this module - writing the document
rather than gathering what goes in it - and exists to hold a claim that would
otherwise be only an assertion in a commit message: that this path can be
driven with no payment provider, no on-call system, no HR source, no read tier
and no model. Every one of those is a plain function here. Before the sources
and the client factory arrived as arguments, this call could not be made at all
without all five installed and reachable.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

import psycopg
import pytest
from agent_postmortem import IncidentEvidence, Sources
from argus_core import connect_from_env, new_id, parse_iso
from argus_core.anomaly import AnomalyThresholds
from argus_core.events import (
    AlertAcknowledged,
    FixAttempted,
    IncidentEvent,
    LogsRetrieved,
    OnsetDetected,
    StatusChanged,
)
from argus_core.llm import ClientFor, LLMClient
from argus_core.models import (
    Alert,
    FailureMode,
    FixOutcome,
    Hypothesis,
    IncidentStatus,
    ModelPolicy,
    OpenedPullRequest,
    PostmortemDocument,
    ToolCall,
    ToolDefinition,
    Transcript,
    Turn,
)
from argus_core.replay import Replay
from argus_incidents.repository import events, hypotheses, incidents
from argus_testkit import Assertion, Scenario, all_of, calling
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import attempting
from orchestrator.gathering import gather_evidence, write_postmortem_for

# How many hours a year the bands are divided by. Any number does: nothing here
# publishes a cost, and the arithmetic that would use it is the agent's own
# suite's business.
DONT_CARE_WORKING_YEAR = 1800.0

# Where the detector draws its lines. Unread by these cases - the metrics
# source answers with nothing - but `Sources` has no default for them, and
# deliberately: thresholds a caller left unwired would be a recovery measured
# against numbers no deployment configured.
DONT_CARE_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)


@pytest.mark.component
def test_the_evidence_spans_the_incident_from_its_start_to_its_end(a_clean_database: None) -> None:
    # The window every figure in the document is measured over. Taken from the
    # incident's own row rather than from the last thing logged, so it does not
    # move when something is written late.
    with connect_from_env() as conn:
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


@pytest.mark.component
def test_the_evidence_carries_the_candidates_the_investigation_ranked(
    a_clean_database: None
) -> None:
    # Including the ones never tried. An investigation that was confident and
    # right and one that ran out of options look identical from their outcome,
    # and the difference is most of what the walk has to say.
    some_cause = "the checkout fallback flag was switched off"
    some_failure_mode = FailureMode.FEATURE_FLAG_TOGGLE
    dont_care_confidence = 0.8

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: hypotheses.record(conn, Hypothesis(
                    incident_id=incident_id,
                    summary=some_cause,
                    failure_mode=some_failure_mode,
                    confidence=dont_care_confidence,
                    supporting_evidence=[]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: evidence.candidates, some_cause)
            )


@pytest.mark.component
def test_the_evidence_carries_the_log_lines_the_incident_read(a_clean_database: None) -> None:
    # From the published account rather than from the log store, which has
    # moved on. What the model explains has to be what Argus actually saw.
    some_window_start = "2026-09-02T11:30:00Z"
    some_window_end = "2026-09-02T12:30:00Z"
    some_log_line = "12:04 ERROR checkout: fallback unavailable"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start=some_window_start,
                    window_end=some_window_end,
                    lines=[some_log_line]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: evidence.log_lines, some_log_line)
            )


@pytest.mark.component
def test_the_evidence_carries_the_timeline_in_the_order_it_happened(a_clean_database: None) -> None:
    # The narration the document is written from - the same lines, from the same
    # renderer, as the page shows. Out of order it is a different incident: a
    # mitigation before the investigation that proposed it explains nothing.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _timeline_begins_with("Received the alert"),
                _timeline_ends_with(str(IncidentStatus.RESOLVED).upper())
            ))


@pytest.mark.component
def test_an_incident_that_has_not_ended_cannot_be_summarised(a_clean_database: None) -> None:
    # A postmortem is written once, when the incident is over. Asked for one
    # earlier, this refuses rather than inventing an end - a duration measured
    # to "now" would be a different number every time it was asked for.
    with connect_from_env() as conn:
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


@pytest.mark.component
def test_an_incident_that_does_not_exist_cannot_be_summarised(a_clean_database: None) -> None:
    # Distinct from an incident still running: there is nothing to summarise
    # rather than nothing yet. Both refuse, and neither invents a document.
    with connect_from_env() as conn:
        Scenario() \
            .when(
                attempting(lambda: gather_evidence(conn, new_id()))
            ) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.component
def test_the_evidence_carries_the_onset_the_investigation_measured(a_clean_database: None) -> None:
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

    with connect_from_env() as conn:
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


@pytest.mark.component
def test_an_incident_whose_onset_was_never_found_carries_none(a_clean_database: None) -> None:
    # A window in which no minute departed from the baseline has no onset to
    # anchor on (spec §9), so the investigation exits without publishing one.
    # The gathering must report that rather than substituting the alert's own
    # time, because the document refuses to cost an incident it cannot date.
    with connect_from_env() as conn:
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


@pytest.mark.component
def test_the_evidence_carries_the_fix_that_was_proposed(a_clean_database: None) -> None:
    # Read off the event rather than left in the timeline for the model to
    # notice. The walk opened the pull request and recorded where; a document
    # that depended on the summary mentioning it loses the address on every run
    # whose prose reads perfectly well without one.
    where_it_can_be_read = "https://github.invalid/ohadraz/io-shop/pull/7"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn,
                    incident_id,
                    FixAttempted(
                        incident_id=incident_id,
                        outcome=FixOutcome.PROPOSED,
                        pull_request=OpenedPullRequest(
                            number=7,
                            url=where_it_can_be_read,
                            branch="argus/fix-abc"
                        ),
                        detail="dont care what the node said"
                    )
                )
            ) \
            .then(
                _carries_the_proposal_at(where_it_can_be_read)
            )


@pytest.mark.component
def test_an_incident_that_read_the_code_and_changed_nothing_carries_no_fix(
    a_clean_database: None
) -> None:
    # The ordinary ending, and a real one: the flag went back and there was
    # nothing in the code to change. The step still published its event, so an
    # evidence bundle reading "there was a fix" off the event's presence rather
    # than off its pull request would invent a proposal.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn,
                    incident_id,
                    FixAttempted(
                        incident_id=incident_id,
                        outcome=FixOutcome.NOT_WARRANTED,
                        pull_request=None,
                        detail="dont care what the node said"
                    )
                )
            ) \
            .then(
                _carries_no_proposal()
            )


@pytest.mark.component
def test_a_postmortem_is_written_from_the_sources_it_was_handed(
    a_clean_database: None
) -> None:
    # The seam M4 bought, exercised. Every provider is a function written here
    # and the model is a stand-in that submits one answer - so this runs with
    # no vendor SDK, no credential and no network, which is the whole claim.
    #
    # Asserted three ways, because there are three things that could be wired
    # wrongly and still return a document: the answer has to reach the page,
    # the sources handed in have to be the ones measured against, and the
    # client has to be asked for per incident rather than shared.
    some_root_cause = "the checkout fallback flag was switched off"
    windows_asked_about: list[tuple[datetime, datetime]] = []
    clients_asked_for: list[Replay] = []

    # Seeded on its own connection and committed by leaving the block: the call
    # under test opens its own, and would not otherwise see any of this.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        incident = incidents.get(conn, incident_id)
        assert incident is not None and incident.ended_at is not None
        the_incidents_own_window = (incident.created_at, incident.ended_at)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: write_postmortem_for(
                incident_id,
                connections=connect_from_env,
                sources=_sources_recording_into(windows_asked_about),
                client_for=_a_model_submitting(some_root_cause, clients_asked_for)
            )
        ) \
        .then(all_of(
            _it_reports_the_root_cause(some_root_cause),
            _the_revenue_source_was_asked_about(the_incidents_own_window,
                                                windows_asked_about),
            _one_client_was_asked_for(clients_asked_for)
        ))


def _sources_recording_into(
    windows_asked_about: list[tuple[datetime, datetime]]
) -> Sources:
    """Every port the document reads, answered without reaching anything.

    All five say they could not answer, which is a real state and the one that
    needs no arithmetic to be right: what is under test here is that the record
    reaches the measurement at all, not what the figures come to. The revenue
    port notes the window it was asked about on the way past, because that is
    the evidence that it was this incident being measured.
    """
    def revenue(started_at: datetime,
                ended_at: datetime) -> Mapping[str, Decimal] | None:
        windows_asked_about.append((started_at, ended_at))

        return None

    return Sources(
        revenue=revenue,
        rates=lambda: None,
        engagement=lambda dont_care_incident_id: None,
        bands=lambda: None,
        metrics=lambda dont_care_start, dont_care_end: [],
        thresholds=DONT_CARE_THRESHOLDS,
        working_hours_a_year=DONT_CARE_WORKING_YEAR,
        reporting_currency="USD"
    )


class _AModelSubmitting:
    """A stand-in that answers with one submitted postmortem, first time.

    The parameter names are the `LLMClient` protocol's own rather than this
    file's `dont_care_` convention: a stand-in whose parameters are named
    differently does not satisfy the protocol, and satisfying it is the point.

    It names no tool of its own. Which tool to call comes from the list it is
    offered, so this knows nothing about what the agent asks for - only that
    whatever was offered is what an answer goes back as.
    """

    def __init__(self, answering: Mapping[str, str]) -> None:
        self._answering = answering

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = 0) -> Turn:
        return Turn(
            text="",
            tool_calls=[ToolCall(id=new_id(),
                                 name=tools[0].name,
                                 arguments=dict(self._answering))],
            input_tokens=0,
            output_tokens=0
        )


def _a_model_submitting(root_cause: str,
                        clients_asked_for: list[Replay]) -> ClientFor:
    """The factory the document asks for a client, noting each time it does.

    A factory rather than a client because the receipt belongs to an incident,
    and this is where that is checked: one document, one client asked for.

    The summary carries no figure. A summary stating an amount is checked
    against the one Argus computed, and with every source answering `None`
    there is no computed figure for it to agree with - so a number here would
    be sent back as invented and this stand-in would answer the same thing
    twice.
    """
    def client_for(replay: Replay, policy: ModelPolicy | None = None) -> LLMClient:
        clients_asked_for.append(replay)

        return _AModelSubmitting({
            "root_cause": root_cause,
            "executive_summary": "The fallback was off and checkout failed."
        })

    return client_for


def _it_reports_the_root_cause(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause != expected:
            raise AssertionError(
                f"Expected the document to report [{expected}], got "
                f"[{document.root_cause}].")

        return True

    return assertion


def _the_revenue_source_was_asked_about(
    expected: tuple[datetime, datetime],
    windows_asked_about: list[tuple[datetime, datetime]]
) -> Assertion[PostmortemDocument]:
    """The incident's own span, among the windows the source was asked about.

    Among rather than alone: the document compares what the service took while
    it was failing against a calm window before it, so the source is asked
    twice and how the baseline is chosen is the agent's business. What this
    holds is narrower and is the part that would be wrong silently - that the
    incident measured was this one, and not some other window that would come
    back looking exactly like it.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if expected not in windows_asked_about:
            raise AssertionError(
                f"Expected the revenue source to be asked about {expected}, "
                f"it was asked about {windows_asked_about}.")

        return True

    return assertion


def _one_client_was_asked_for(
    clients_asked_for: list[Replay]
) -> Assertion[PostmortemDocument]:
    """One document, one client.

    A client is asked for per incident because the receipt it keeps is filed
    under one - so a path that asked for none took a shared one from somewhere,
    and one that asked twice would file one document's calls under two.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if len(clients_asked_for) != 1:
            raise AssertionError(
                f"Expected exactly one client to be asked for, "
                f"{len(clients_asked_for)} were.")

        return True

    return assertion


def _the_evidence_after_publishing(conn: psycopg.Connection,
                                   incident_id: str,
                                   event: IncidentEvent) -> IncidentEvidence:
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


def _carries_the_proposal_at(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        proposed = evidence.pull_request.url if evidence.pull_request else None

        if proposed != expected:
            raise AssertionError(
                f"expected the fix proposed at [{expected}], got [{proposed}]")

        return True

    return assertion


def _carries_no_proposal() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.pull_request is not None:
            raise AssertionError(
                f"expected no fix proposed, got [{evidence.pull_request}]")

        return True

    return assertion


def _an_incident_that_ended(conn: psycopg.Connection) -> str:
    """An incident with both a row and an account of itself.

    The events as well as the rows, because the document is written from the
    account now rather than from the status column: an incident whose rows
    moved and whose story says nothing is one the postmortem has nothing to
    read.
    """
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    incident_id = incidents.create(conn, some_alert)
    events.record(conn, AlertAcknowledged(incident_id=incident_id, alert=some_alert))
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
    )
    events.record(
        conn,
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
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
                f"Expected the evidence to start at [{expected}], got [{evidence.started_at}].")

        return True

    return assertion


def _ends_at(expected: object) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.ended_at != expected:
            raise AssertionError(
                f"Expected the evidence to end at [{expected}], got [{evidence.ended_at}].")

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
            raise AssertionError(f"Expected [{expected}] among {lines}.")

        return True

    return assertion


def _timeline_begins_with(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if not evidence.timeline or expected not in evidence.timeline[0]:
            raise AssertionError(
                f"Expected the timeline to open on [{expected}], got {evidence.timeline}.")

        return True

    return assertion


def _timeline_ends_with(expected: str) -> Assertion[IncidentEvidence]:
    """Where the incident finished, in the account's own words.

    Both ends rather than one: a timeline holding only its first line is in
    order trivially, and the order is the whole claim.
    """
    def assertion(evidence: IncidentEvidence) -> bool:
        if not evidence.timeline or expected not in evidence.timeline[-1]:
            raise AssertionError(
                f"Expected the timeline to close on [{expected}], got {evidence.timeline}.")

        return True

    return assertion


