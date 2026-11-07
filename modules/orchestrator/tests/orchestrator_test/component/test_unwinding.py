"""What the unwind did with a change, kept on its row and said, as one write.

The row decides what a later pass does: a change kept as settled is passed over.
Kept and committed before its line, a stop between the two would leave a row
saying put back and no line saying so - and the next pass, reading the row,
would never say it either. So the two share a transaction, and the line is
written in a savepoint of its own: it commits with the row, and it fails alone.
"""

from __future__ import annotations

import pytest
from argus_core import connect_from_env, utc_now
from argus_core.events import ChangeUndone, IncidentEvent, Publisher
from argus_core.models import REVERT_FEATURE_FLAG, Alert, FlagUndo, Undone, Verdict
from argus_incidents import events_into_connection
from argus_incidents.repository import events, hypotheses, incidents, taken_actions
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.unwinding import undone_recorded_through

from orchestrator_test.framework.builders import a_determined_hypothesis

SOME_FLAG = "monthly-spend-feature"


@pytest.mark.component
def test_what_the_unwind_did_is_not_durable_before_the_line_that_says_it(
    a_clean_database: None
) -> None:
    incident_id, action_id = _a_change_a_withdrawn_walk_left()
    seen_mid_write: list[Undone | None] = []

    record_undone = undone_recorded_through(
        connect_from_env,
        publisher_for=lambda conn: _a_publisher_that_looks_at_the_row(
            seen_mid_write, incident_id, events_into_connection(conn)
        )
    )

    Scenario() \
        .given(
            action_id
        ) \
        .when(
            lambda: record_undone(action_id, _put_back(incident_id))
        ) \
        .then(all_of(
            _nothing_outside_saw_it_kept(seen_mid_write),
            _the_row_keeps(incident_id, Undone.RESTORED),
            _the_line_says(incident_id, Undone.RESTORED)
        ))


@pytest.mark.component
def test_what_the_unwind_did_survives_a_line_that_could_not_be_written(
    a_clean_database: None
) -> None:
    # The savepoint, from the side that costs something. The flag is already
    # back by the time this is written, and the row is what tells a later pass
    # so - losing it to a sentence nobody could write would make the account
    # load-bearing (spec §4 principle 8).
    incident_id, action_id = _a_change_a_withdrawn_walk_left()

    record_undone = undone_recorded_through(
        connect_from_env, publisher_for=lambda dont_care_conn: _nobody_can_write
    )

    Scenario() \
        .given(
            action_id
        ) \
        .when(
            lambda: record_undone(action_id, _put_back(incident_id))
        ) \
        .then(all_of(
            _the_row_keeps(incident_id, Undone.RESTORED),
            _nothing_was_said(incident_id)
        ))


def _a_change_a_withdrawn_walk_left() -> tuple[str, str]:
    """An incident whose walk changed a flag and was withdrawn before judging
    it, and the id of the change's row - which is how the unwind holds it."""
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, at=utc_now())
        candidate = a_determined_hypothesis(incident_id)
        hypotheses.record(conn, candidate)
        taken_actions.record(
            conn,
            incident_id,
            hypothesis_id=candidate.id,
            action_type=REVERT_FEATURE_FLAG,
            subject=SOME_FLAG,
            outcome=Verdict.STOPPED,
            undo_descriptor=FlagUndo(flag=SOME_FLAG, was_enabled=True),
            at=utc_now(),
            left_behind_known=True
        )

        return incident_id, taken_actions.get_by_incident(conn, incident_id)[0].id


def _put_back(incident_id: str) -> ChangeUndone:
    return ChangeUndone(incident_id=incident_id, subject=SOME_FLAG,
                        outcome=Undone.RESTORED, detail="dont care")


def _nobody_can_write(dont_care_event: IncidentEvent) -> None:
    """A subscriber having the worst day it can have."""
    raise RuntimeError("the event store refused the write")


def _a_publisher_that_looks_at_the_row(seen: list[Undone | None],
                                       incident_id: str,
                                       then_publishing: Publisher) -> Publisher:
    """Reads the row back from a second connection while the first still holds
    what was kept on it open, then lets the real subscriber write."""
    def publisher(event: IncidentEvent) -> None:
        with connect_from_env() as another_connection:
            seen.extend(action.undone for action
                        in taken_actions.get_by_incident(another_connection, incident_id))

        then_publishing(event)

    return publisher


def _nothing_outside_saw_it_kept(seen: list[Undone | None]) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        if not seen:
            raise AssertionError(
                "Expected the line to have been written at all - nothing looked "
                "from outside, so nothing was asserted."
            )

        if any(undone is not None for undone in seen):
            raise AssertionError(
                f"Expected a reader outside the write to see nothing kept on the "
                f"row while the line was still being written, got {seen}."
            )

        return True

    return assertion


def _the_row_keeps(incident_id: str, expected: Undone) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
            kept = [action.undone for action in taken_actions.get_by_incident(conn, incident_id)]

        if kept != [expected]:
            raise AssertionError(
                f"Expected the change's row to keep [{expected}], the incident's rows "
                f"keep {kept}."
            )

        return True

    return assertion


def _the_line_says(incident_id: str, expected: Undone) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
            said = [event.outcome for event in events.get_by_incident(conn, incident_id)
                    if isinstance(event, ChangeUndone)]

        if said != [expected]:
            raise AssertionError(
                f"Expected one line saying the change was [{expected}], got {said}."
            )

        return True

    return assertion


def _nothing_was_said(incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
            said = events.get_by_incident(conn, incident_id)

        if said:
            raise AssertionError(
                f"Expected a refused line to leave no event behind, got "
                f"{[type(event).__name__ for event in said]}."
            )

        return True

    return assertion
