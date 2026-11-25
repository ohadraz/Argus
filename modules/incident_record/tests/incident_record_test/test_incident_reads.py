"""One incident, read through the role every reader holds.

What the role owes a reader is the incident as the tables hold it, in domain
values - and the connection it was asked on. Built on a connection, it reads
what that connection sees, a write its caller has not committed included.
Built over connections, it opens nothing until asked and then one connection a
question.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, the_answer_was
from core.events import AgentInvoked, IncidentEvent
from core.models import Actor, Alert, FailureMode, Hypothesis
from incident_record import incident_reads_on, incident_reads_over
from incident_record.repository import events, hypotheses
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for
from incident_record_test.framework.opening import (
    CountedConnections,
    connections_never_opened,
    it_was_built,
)

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
SOME_SUMMARY = "a feature flag was toggled on just before the errors began"
SOME_CONFIDENCE = 0.9
# An incident no row was ever written for.
NO_SUCH_INCIDENT = "00000000-0000-4000-8000-000000000000"
# A candidate nothing was ever claimed for.
NO_SUCH_CANDIDATE = "00000000-0000-4000-8000-000000000001"
NOTHING_SPENT = 0
# How many questions the counting case asks, one connection each.
TWO_QUESTIONS = 2


@pytest.mark.component
def test_an_incident_just_opened_reads_as_nothing_done_yet() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        reads = incident_reads_on(conn)

        Scenario() \
            .when(lambda: _everything_read_about(reads, incident_id)) \
            .then(the_answer_was({
                "incident": incident_id,
                "account": [],
                "candidates": [],
                "actions": [],
                "action_for": None,
                "claimed_fix": None,
                "leads": [],
                "postmortem": None,
                "synopsis": None,
                "tokens_spent": NOTHING_SPENT
            }))


@pytest.mark.component
def test_an_incident_nobody_opened_reads_as_none() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .when(lambda: incident_reads_on(conn).incident(NO_SUCH_INCIDENT)) \
            .then(the_answer_was(None))


@pytest.mark.component
def test_reads_on_a_connection_see_what_its_caller_has_not_yet_committed() -> None:
    # The whole of why the role is built on the caller's connection: a reader
    # composing an answer reads what its connection sees, one moment where the
    # caller holds it at one.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        some_line = AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR)
        some_candidate = _a_candidate_of(incident_id)

        Scenario() \
            .given(
                calling(lambda: events.record(conn, some_line)),
                calling(lambda: hypotheses.record(conn, some_candidate))
            ) \
            .when(lambda: (incident_reads_on(conn).account(incident_id),
                           incident_reads_on(conn).candidates(incident_id))) \
            .then(all_of(
                _the_account_is([some_line]),
                _the_candidates_are([some_candidate.id])
            ))


@pytest.mark.component
def test_reads_over_connections_open_nothing_when_built() -> None:
    Scenario() \
        .when(lambda: incident_reads_over(connections_never_opened())) \
        .then(it_was_built())


@pytest.mark.component
def test_reads_over_connections_ask_each_question_on_a_connection_of_its_own() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

    counted = CountedConnections()
    reads = incident_reads_over(counted)

    Scenario() \
        .given(calling(lambda: reads.incident(incident_id))) \
        .when(lambda: reads.account(incident_id)) \
        .then(_connections_opened(counted, TWO_QUESTIONS))


def _everything_read_about(reads: Any, incident_id: str) -> dict[str, Any]:
    """Every read the role offers about one incident, by name - the row by its
    id, since the row's other fields are the intake's to test."""
    incident = reads.incident(incident_id)

    return {
        "incident": incident.id if incident is not None else None,
        "account": reads.account(incident_id),
        "candidates": reads.candidates(incident_id),
        "actions": reads.actions(incident_id),
        "action_for": reads.action_for(incident_id, NO_SUCH_CANDIDATE),
        "claimed_fix": reads.claimed_fix(incident_id),
        "leads": reads.leads(incident_id),
        "postmortem": reads.postmortem(incident_id),
        "synopsis": reads.synopsis(incident_id),
        "tokens_spent": reads.tokens_spent(incident_id)
    }


def _a_candidate_of(incident_id: str) -> Hypothesis:
    return Hypothesis(incident_id=incident_id,
                      summary=SOME_SUMMARY,
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                      confidence=SOME_CONFIDENCE,
                      supporting_evidence=[])


def _the_account_is(expected: list[IncidentEvent]
                    ) -> Assertion[tuple[list[IncidentEvent], list[Hypothesis]]]:
    def assertion(read: tuple[list[IncidentEvent], list[Hypothesis]]) -> bool:
        account, _ = read

        if account != expected:
            raise AssertionError(
                f"Expected the account read on the caller's connection to be {expected}, "
                f"and it was {account}."
            )

        return True

    return assertion


def _the_candidates_are(expected: list[str]
                        ) -> Assertion[tuple[list[IncidentEvent], list[Hypothesis]]]:
    def assertion(read: tuple[list[IncidentEvent], list[Hypothesis]]) -> bool:
        _, candidates = read
        ids = [candidate.id for candidate in candidates]

        if ids != expected:
            raise AssertionError(
                f"Expected the candidates read on the caller's connection to be {expected}, "
                f"and they were {ids}."
            )

        return True

    return assertion


def _connections_opened(counted: CountedConnections, expected: int) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        if counted.opened != expected:
            raise AssertionError(
                f"Expected {expected} connections opened, one a question, and "
                f"{counted.opened} were."
            )

        return True

    return assertion
