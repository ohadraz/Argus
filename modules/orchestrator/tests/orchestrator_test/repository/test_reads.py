from __future__ import annotations

from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import actions, hypotheses, incidents

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

"""The read paths an incident view needs, which the graph never had a use for.

The repositories were written for what the walk does - record a hypothesis,
update its outcome, take the latest one. Reading an incident back afterwards
asks different questions: every candidate rather than the last, the actions in
the order they were taken, and which incidents there are at all. Those are the
three gaps, and they are here.
"""


@pytest.mark.integration
def test_every_candidate_of_an_incident_comes_back_in_rank_order() -> None:
    # `get_latest_by_incident` answers with one hypothesis, which is exactly the
    # shape that hides a walk: an incident resolved on its second candidate
    # looks, through that lens, like an incident with one candidate.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_candidate_recorded_for = partial(_a_candidate_recorded_for, conn)
        the_candidates_read_back_are = partial(_the_candidates_read_back_are, conn)

        incident_id = an_incident_created_for(some_alert)

        def three_candidates_are_recorded_out_of_order() -> None:
            a_candidate_recorded_for(incident_id, subject="third", rank=3)
            a_candidate_recorded_for(incident_id, subject="first", rank=1)
            a_candidate_recorded_for(incident_id, subject="second", rank=2)

        Scenario() \
            .when(
                three_candidates_are_recorded_out_of_order
            ) \
            .then(
                the_candidates_read_back_are(incident_id, ["first", "second", "third"])
            )


@pytest.mark.integration
def test_an_untried_candidate_comes_back_as_untried() -> None:
    # An incident resolved before its lowest-ranked candidates were reached
    # still has them, and the difference between "tried and refuted" and "never
    # reached" is the difference between a walk and a lucky guess.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_candidate_recorded_for = partial(_a_candidate_recorded_for, conn)
        the_candidate_ranked = partial(_the_candidate_ranked, conn)

        incident_id = an_incident_created_for(some_alert)
        tried = a_candidate_recorded_for(incident_id, subject="tried", rank=1)
        a_candidate_recorded_for(incident_id, subject="never reached", rank=2)

        Scenario() \
            .when(
                lambda: hypotheses.record_outcome(
                    conn, tried, tested=True, result="refuted"
                )
            ) \
            .then(all_of(
                the_candidate_ranked(incident_id, 1, tested=True, result="refuted"),
                the_candidate_ranked(incident_id, 2, tested=False, result=None),
            ))


@pytest.mark.integration
def test_an_incident_with_no_candidates_reads_as_empty_rather_than_missing() -> None:
    # An incident that escalated before forming a hypothesis is a real incident
    # with nothing to show, which is not the same as an unknown incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)

        incident_id = an_incident_created_for(some_alert)

        assert hypotheses.get_all_by_incident(conn, incident_id) == []


@pytest.mark.integration
def test_the_actions_of_an_incident_come_back_in_the_order_they_were_taken() -> None:
    # A walk's actions are a sequence - tried, undone, tried again - and read
    # back in any other order they describe a different incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_candidate_recorded_for = partial(_a_candidate_recorded_for, conn)
        the_actions_read_back_are = partial(_the_actions_read_back_are, conn)

        incident_id = an_incident_created_for(some_alert)
        first = a_candidate_recorded_for(incident_id, subject="first", rank=1)
        second = a_candidate_recorded_for(incident_id, subject="second", rank=2)

        def two_actions_are_taken() -> None:
            for candidate, outcome in ((first, "refuted"), (second, "confirmed")):
                actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    outcome=outcome,
                    undo_descriptor={"flag": "dont-care"},
                )

        Scenario() \
            .when(
                two_actions_are_taken
            ) \
            .then(
                the_actions_read_back_are(incident_id, ["refuted", "confirmed"])
            )


@pytest.mark.integration
def test_an_action_comes_back_naming_the_candidate_it_was_taken_for() -> None:
    # The association the action table now stores. A reader following the key
    # can attribute an action without matching the flag the action and the
    # candidate happen to share.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_candidate_recorded_for = partial(_a_candidate_recorded_for, conn)

        incident_id = an_incident_created_for(some_alert)
        candidate_id = a_candidate_recorded_for(incident_id, subject="a-flag", rank=1)
        actions.record(
            conn,
            incident_id,
            hypothesis_id=candidate_id,
            action_type="revert-feature-flag",
            outcome="confirmed",
            undo_descriptor={"flag": "a-flag"},
        )

        taken = actions.get_by_incident(conn, incident_id)

        assert len(taken) == 1, f"Expected one action, got {len(taken)}."
        assert taken[0].hypothesis_id == candidate_id, (
            f"Expected the action to name {candidate_id}, got {taken[0].hypothesis_id}."
        )


@pytest.mark.integration
def test_incidents_come_back_newest_first() -> None:
    # The history view opens on what just happened. Oldest-first would put the
    # incident somebody is looking for at the bottom of the page.
    an_older_alert = Alert(service="older-service", alert_name="HighErrorRate")
    a_newer_alert = Alert(service="newer-service", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)

        older = an_incident_created_for(an_older_alert)
        newer = an_incident_created_for(a_newer_alert)

        recent = [incident.id for incident in incidents.get_recent(conn)]

        assert recent.index(newer) < recent.index(older), (
            "Expected the newer incident to come back before the older one."
        )


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _a_candidate_recorded_for(conn: psycopg.Connection,
                              incident_id: str,
                              subject: str,
                              rank: int) -> str:
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary=f"dont care - {subject}",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject,
        rank=rank,
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _the_candidates_read_back_are(conn: psycopg.Connection,
                                  incident_id: str,
                                  subjects: list[str]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        found = [
            candidate.subject
            for candidate in hypotheses.get_all_by_incident(conn, incident_id)
        ]

        assert found == subjects, f"Expected candidates {subjects}, got {found}."

        return True

    return assertion


def _the_candidate_ranked(conn: psycopg.Connection,
                          incident_id: str,
                          rank: int,
                          tested: bool,
                          result: str | None) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        candidate = next(
            found
            for found in hypotheses.get_all_by_incident(conn, incident_id)
            if found.rank == rank
        )

        assert candidate.tested is tested, (
            f"Expected rank {rank} tested={tested}, got {candidate.tested}."
        )
        assert candidate.result == result, (
            f"Expected rank {rank} result={result!r}, got {candidate.result!r}."
        )

        return True

    return assertion


def _the_actions_read_back_are(conn: psycopg.Connection,
                               incident_id: str,
                               outcomes: list[str]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        found = [taken.outcome for taken in actions.get_by_incident(conn, incident_id)]

        assert found == outcomes, f"Expected outcomes {outcomes}, got {found}."

        return True

    return assertion
