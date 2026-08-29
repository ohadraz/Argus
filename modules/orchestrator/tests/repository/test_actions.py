from __future__ import annotations

from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import actions, incidents

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
        the_action_row_says = partial(_the_action_row_says, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: actions.record(
                    conn,
                    incident_id,
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
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .when(
                lambda: actions.record(
                    conn,
                    incident_id,
                    action_type="revert-feature-flag",
                    outcome="escalated",
                    undo_descriptor={},
                )
            ) \
            .then(
                the_action_row_carries(incident_id, None)
            )


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _the_action_row_says(conn: psycopg.Connection,
                         incident_id: str,
                         action_type: str,
                         outcome: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        recorded_type, recorded_outcome, _ = _the_only_action_row(conn, incident_id)

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
        _, _, recorded = _the_only_action_row(conn, incident_id)

        assert recorded == undo_descriptor, (
            f"Expected undo descriptor {undo_descriptor}, got {recorded}."
        )

        return True

    return assertion


def _the_only_action_row(conn: psycopg.Connection,
                         incident_id: str) -> tuple[Any, Any, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT type, outcome, undo_descriptor FROM action WHERE incident_id = %s",
            (incident_id,),
        )
        rows = cursor.fetchall()

    assert len(rows) == 1, f"Expected exactly one action row, got {len(rows)}."

    return rows[0]
