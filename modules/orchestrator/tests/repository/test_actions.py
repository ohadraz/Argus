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


@pytest.mark.integration
def test_record_writes_the_action_with_its_outcome_and_undo_descriptor() -> None:
    # The record of an incident has to say what was changed and what would put
    # it back. An outcome alone leaves a human reading the row afterwards
    # knowing a flag was touched and not which state it had been in.
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")
    some_undo_descriptor = {
        "tool": "set_feature_flag",
        "flag": "monthly-spend-feature",
        "environment": "production",
        "was_enabled": True,
    }

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_says = partial(_the_action_row_says, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    outcome="confirmed",
                    undo_descriptor=some_undo_descriptor,
                )
            ) \
            .then(all_of(
                the_action_row_says(
                    incident_id, action_type="revert-feature-flag", outcome="confirmed"
                ),
                the_action_row_carries(incident_id, some_undo_descriptor),
            ))


@pytest.mark.integration
def test_an_action_with_nothing_to_undo_is_recorded_without_a_descriptor() -> None:
    # An action that never reached the provider changed nothing, so there is
    # nothing to put back - and a row claiming otherwise would send a human to
    # undo a change that was never made.
    some_service = "buki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    outcome="escalated",
                    undo_descriptor={},
                )
            ) \
            .then(
                the_action_row_carries(incident_id, None)
            )


@pytest.mark.integration
def test_an_action_names_the_candidate_it_was_taken_for() -> None:
    # The association is stored rather than inferred. Recovering it afterwards
    # means matching the flag the action and the hypothesis happen to share,
    # which is only ever right because the walk refuses to act on one subject
    # twice - a rule about not retrying a move, not about identity. Argus knows
    # which candidate it is acting on at the moment it writes the row, and this
    # is that knowledge surviving.
    some_alert = Alert(service="kukibuki-service", alert_name="HighErrorRate")

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_names = partial(_the_action_row_names, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    outcome="refuted",
                    undo_descriptor={"tool": "set_feature_flag", "was_enabled": False},
                )
            ) \
            .then(
                the_action_row_names(incident_id, hypothesis_id)
            )


@pytest.mark.integration
def test_two_candidates_naming_one_subject_keep_their_own_actions() -> None:
    # What the stored association buys that the subject match could not. Two
    # candidates about the same flag are indistinguishable to anything matching
    # on subject, so both actions would be attributed to whichever candidate was
    # found first. The walk forbids this today; the data model should not depend
    # on its continuing to.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_contested_flag = "monthly-spend-feature"

    with psycopg.connect(DATABASE_URL) as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        each_action_names_its_own_candidate = partial(
            _each_action_names_its_own_candidate, conn
        )

        incident_id = an_incident_created_for(some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=2)

        def an_action_is_taken_for_each() -> None:
            for candidate, outcome in ((first, "refuted"), (second, "confirmed")):
                actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    outcome=outcome,
                    undo_descriptor={"flag": the_contested_flag},
                )

        Scenario() \
            .when(
                an_action_is_taken_for_each
            ) \
            .then(
                each_action_names_its_own_candidate(incident_id, {first, second})
            )


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _a_hypothesis_recorded_for(conn: psycopg.Connection,
                               incident_id: str,
                               subject: str | None = None,
                               rank: int = 1) -> str:
    """A candidate an action can point at.

    An action's hypothesis is a foreign key, so a row has to exist for it to
    name - which makes this the smallest hypothesis the column will accept
    rather than anything a test asserts on.
    """
    hypothesis = Hypothesis(
        incident_id=incident_id,
        summary="dont care",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject,
        rank=rank,
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _the_action_row_says(conn: psycopg.Connection,
                         incident_id: str,
                         action_type: str,
                         outcome: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        recorded_type, recorded_outcome, _, _ = _the_only_action_row(conn, incident_id)

        assert recorded_type == action_type, (
            f"Expected type {action_type}, got {recorded_type}."
        )
        assert recorded_outcome == outcome, (
            f"Expected outcome {outcome}, got {recorded_outcome}."
        )

        return True

    return assertion


def _the_action_row_carries(conn: psycopg.Connection,
                            incident_id: str,
                            undo_descriptor: dict[str, Any] | None) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, recorded, _ = _the_only_action_row(conn, incident_id)

        assert recorded == undo_descriptor, (
            f"Expected undo descriptor {undo_descriptor}, got {recorded}."
        )

        return True

    return assertion


def _the_action_row_names(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, _, recorded = _the_only_action_row(conn, incident_id)

        assert str(recorded) == hypothesis_id, (
            f"Expected the action to name hypothesis {hypothesis_id}, got {recorded}."
        )

        return True

    return assertion


def _each_action_names_its_own_candidate(conn: psycopg.Connection,
                                         incident_id: str,
                                         candidates: set[str]) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT hypothesis_id FROM action WHERE incident_id = %s",
                (incident_id,),
            )
            named = {str(row[0]) for row in cursor.fetchall()}

        assert named == candidates, (
            f"Expected the two actions to name {candidates}, got {named}."
        )

        return True

    return assertion


def _the_only_action_row(conn: psycopg.Connection,
                         incident_id: str) -> tuple[Any, Any, Any, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT type, outcome, undo_descriptor, hypothesis_id "
            "FROM action WHERE incident_id = %s",
            (incident_id,),
        )
        rows = cursor.fetchall()

    assert len(rows) == 1, f"Expected exactly one action row, got {len(rows)}."

    return rows[0]
