"""Every write the walk makes, through the role it makes them with.

What the role owes the walk is the writes on the connection the walk holds, and
no commit of its own: each is one unit of work with the line published beside
it, so a write the walk rolls back must leave nothing behind. And what the
walk asks back - whether the incident moved, how much a step run again took
back - is the answer to the write it made.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, calling, the_answer_was
from core import utc_now
from core.events import AgentInvoked
from core.models import Actor, Alert, FailureMode, Hypothesis, IncidentStatus
from incident_record import TheWalksWrites, incident_reads_on, the_walks_writes_on, within_step
from incident_record.repository import events
from postgres import connect_from_env

from incident_record_test.framework.builders import an_incident_created_for

DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
SOME_SUMMARY = "a feature flag was toggled on just before the errors began"
SOME_CONFIDENCE = 0.9
SOME_RESULT = "refuted: the errors went on after the flag was put back"
SOME_STEP = 4
# One line and one candidate, written in the step taken back.
WHAT_THE_STEP_WROTE = 2


@pytest.mark.component
def test_a_transition_moves_the_incident_and_says_it_did() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)

        Scenario() \
            .when(lambda: the_walks_writes_on(conn).transition(
                incident_id, IncidentStatus.INVESTIGATING, at=utc_now())) \
            .then(all_of(
                the_answer_was(True),
                _the_incident_is(conn, incident_id, IncidentStatus.INVESTIGATING)
            ))


@pytest.mark.component
def test_a_write_the_walk_rolls_back_leaves_nothing_behind() -> None:
    # The role never commits: the walk's unit of work does, with the line
    # published beside the write - so the walk rolling back takes both.
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        conn.commit()

        Scenario() \
            .given(
                # Read before the write, so a role that committed the move
                # would leave the incident somewhere this does not say.
                opened_with := _the_status_opened_with(incident_id),
                calling(lambda: the_walks_writes_on(conn).transition(
                    incident_id, IncidentStatus.INVESTIGATING, at=utc_now())),
                calling(conn.rollback)
            ) \
            .when(lambda: incident_reads_on(conn).incident(incident_id)) \
            .then(_the_status_read_is(opened_with))


@pytest.mark.component
def test_what_came_of_a_candidate_is_written_onto_it() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        some_candidate = _a_candidate_of(incident_id)
        writes = the_walks_writes_on(conn)

        Scenario() \
            .given(
                calling(lambda: _written_within_a_step(writes, some_candidate)),
                calling(lambda: writes.outcome(some_candidate.id, tested=True,
                                               result=SOME_RESULT))
            ) \
            .when(lambda: incident_reads_on(conn).candidates(incident_id)) \
            .then(_the_only_candidate_came_to(tested=True, result=SOME_RESULT))


@pytest.mark.component
def test_taking_back_a_step_takes_its_lines_and_its_candidates() -> None:
    with connect_from_env() as conn:
        incident_id = an_incident_created_for(conn, DONT_CARE_ALERT)
        writes = the_walks_writes_on(conn)

        Scenario() \
            .given(calling(lambda: _a_step_that_said_and_formed(conn, incident_id))) \
            .when(lambda: writes.take_back_step(incident_id, SOME_STEP)) \
            .then(all_of(
                the_answer_was(WHAT_THE_STEP_WROTE),
                _nothing_of_the_step_is_left(conn, incident_id)
            ))


def _a_candidate_of(incident_id: str) -> Hypothesis:
    return Hypothesis(incident_id=incident_id,
                      summary=SOME_SUMMARY,
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                      confidence=SOME_CONFIDENCE,
                      supporting_evidence=[])


def _written_within_a_step(writes: TheWalksWrites, candidate: Hypothesis) -> None:
    """A candidate written as the walk writes one: inside a step."""
    with within_step(SOME_STEP):
        writes.hypothesis(candidate)


def _a_step_that_said_and_formed(conn: psycopg.Connection, incident_id: str) -> None:
    """One line said and one candidate formed, both inside the step."""
    with within_step(SOME_STEP):
        events.record(conn, AgentInvoked(incident_id=incident_id, agent=Actor.INVESTIGATOR))
        the_walks_writes_on(conn).hypothesis(_a_candidate_of(incident_id))


def _the_status_opened_with(incident_id: str) -> IncidentStatus:
    """The status an incident is opened in, read on a connection of its own."""
    with connect_from_env() as conn:
        incident = incident_reads_on(conn).incident(incident_id)
        assert incident is not None, f"Expected incident {incident_id} to exist."

        return incident.status


def _the_incident_is(conn: psycopg.Connection, incident_id: str,
                     expected: IncidentStatus) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        incident = incident_reads_on(conn).incident(incident_id)
        status = incident.status if incident is not None else None

        if status != expected:
            raise AssertionError(f"Expected the incident to be {expected}, and it is {status}.")

        return True

    return assertion


def _the_status_read_is(expected: IncidentStatus) -> Assertion[object]:
    def assertion(incident: object) -> bool:
        status = getattr(incident, "status", None)

        if status != expected:
            raise AssertionError(
                f"Expected the incident still to be {expected} once the walk rolled "
                f"back, and it is {status}."
            )

        return True

    return assertion


def _the_only_candidate_came_to(*, tested: bool, result: str) -> Assertion[list[Hypothesis]]:
    def assertion(candidates: list[Hypothesis]) -> bool:
        came_to = [(candidate.tested, candidate.result) for candidate in candidates]

        if came_to != [(tested, result)]:
            raise AssertionError(
                f"Expected one candidate, come to {(tested, result)}, and the "
                f"candidates came to {came_to}."
            )

        return True

    return assertion


def _nothing_of_the_step_is_left(conn: psycopg.Connection,
                                 incident_id: str) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        reads = incident_reads_on(conn)
        left = (reads.account(incident_id), reads.candidates(incident_id))

        if left != ([], []):
            raise AssertionError(
                f"Expected nothing of the step to be left, and found {left}."
            )

        return True

    return assertion
