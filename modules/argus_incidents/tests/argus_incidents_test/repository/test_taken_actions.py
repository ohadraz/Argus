from __future__ import annotations

from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core import connect_from_env
from argus_core.models import Alert, CauseType, FlagUndo, Hypothesis, UndoDescriptor
from argus_incidents.repository import hypotheses, incidents, taken_actions
from argus_testkit import Assertion, Scenario, all_of


@pytest.mark.integration
def test_record_writes_the_action_with_its_outcome_and_undo_descriptor() -> None:
    # The record of an incident has to say what was changed and what would put
    # it back. An outcome alone leaves a human reading the row afterwards
    # knowing a flag was touched and not which state it had been in.
    some_service = "kuki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")
    some_undo_descriptor = FlagUndo(
        flag="monthly-spend-feature",
        was_enabled=True,
        environment="production"
    )

    with connect_from_env() as conn:
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
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    outcome="confirmed",
                    undo_descriptor=some_undo_descriptor
                )
            ) \
            .then(all_of(
                the_action_row_says(
                    incident_id, action_type="revert-feature-flag", outcome="confirmed"
                ),
                the_action_row_carries(incident_id, some_undo_descriptor)
            ))


@pytest.mark.integration
def test_an_action_with_nothing_to_undo_is_recorded_without_a_descriptor() -> None:
    # An action that never reached the provider changed nothing, so there is
    # nothing to put back - and a row claiming otherwise would send a human to
    # undo a change that was never made.
    some_service = "buki-service"
    some_alert = Alert(service=some_service, alert_name="HighErrorRate")

    with connect_from_env() as conn:
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
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome="escalated",
                    undo_descriptor=None
                )
            ) \
            .then(
                the_action_row_carries(incident_id, None)
            )


@pytest.mark.integration
def test_an_action_names_the_subject_it_changed() -> None:
    # The row has to say what was changed, not only that something was. Argus
    # holds the subject at the moment it claims the action - it is the candidate
    # it is acting on - and a column that is read back but never written is a
    # question every later reader has to answer by guessing.
    #
    # Two readers already depend on it and neither can recover it: the
    # postmortem's account of what was done renders the action and its subject
    # in one line, and long-term memory - whose whole content is which subjects
    # were tried and what each attempt was worth - keeps nothing at all for an
    # attempt that names none.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_flag_that_was_changed = "monthly-spend-feature"

    with connect_from_env() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)
        the_action_read_back_changed = partial(_the_action_read_back_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject=the_flag_that_was_changed,
                    outcome="confirmed",
                    undo_descriptor=FlagUndo(
                        flag=the_flag_that_was_changed, was_enabled=True
                    )
                )
            ) \
            .then(all_of(
                the_action_row_changed(incident_id, the_flag_that_was_changed),
                the_action_read_back_changed(incident_id, the_flag_that_was_changed)
            ))


@pytest.mark.integration
def test_an_action_claimed_and_not_yet_finished_already_names_its_subject() -> None:
    # The subject is written by the claim rather than by the verdict, because
    # the claim is the write that happens before anything is done - and the one
    # case this table exists to answer is a worker that stopped in between. A
    # row found with no outcome has to say what change is out there; recovering
    # that from the descriptor of an action that may never have reached the
    # provider is the reconstruction the column was added to avoid.
    some_alert = Alert(service="io-shop", alert_name="HighLatency")
    the_flag_that_was_changed = "checkout-v2"

    with connect_from_env() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject=the_flag_that_was_changed
                )
            ) \
            .then(
                the_action_row_changed(incident_id, the_flag_that_was_changed)
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

    with connect_from_env() as conn:
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
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    outcome="refuted",
                    undo_descriptor=FlagUndo(flag="monthly-spend-feature", was_enabled=False)
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

    with connect_from_env() as conn:
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
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject=the_contested_flag,
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag=the_contested_flag, was_enabled=True)
                )

        Scenario() \
            .when(
                an_action_is_taken_for_each
            ) \
            .then(
                each_action_names_its_own_candidate(incident_id, {first, second})
            )


@pytest.mark.integration
def test_the_actions_of_an_incident_come_back_in_the_order_they_were_taken() -> None:
    # A walk's actions are a sequence - tried, undone, tried again - and read
    # back in any other order they describe a different incident.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        an_incident_created_for = partial(_an_incident_created_for, conn)
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_actions_read_back_are = partial(_the_actions_read_back_are, conn)

        incident_id = an_incident_created_for(some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject="first", rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject="second", rank=2)

        def two_actions_are_taken() -> None:
            for candidate, outcome in ((first, "refuted"), (second, "confirmed")):
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject="dont-care",
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True)
                )

        Scenario() \
            .when(
                two_actions_are_taken
            ) \
            .then(
                the_actions_read_back_are(incident_id, ["refuted", "confirmed"])
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
        rank=rank
    )
    hypotheses.record(conn, hypothesis)

    return hypothesis.id


def _the_action_row_says(conn: psycopg.Connection,
                         incident_id: str,
                         action_type: str,
                         outcome: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        recorded_type, recorded_outcome, _, _, _ = _the_only_action_row(conn, incident_id)

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
                            undo_descriptor: UndoDescriptor | None) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, recorded, _, _ = _the_only_action_row(conn, incident_id)
        expected = (
            undo_descriptor.model_dump(mode="json")
            if undo_descriptor is not None else None
        )

        assert recorded == expected, (
            f"Expected undo descriptor {expected}, got {recorded}."
        )

        return True

    return assertion


def _the_action_row_names(conn: psycopg.Connection,
                          incident_id: str,
                          hypothesis_id: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        _, _, _, recorded, _ = _the_only_action_row(conn, incident_id)

        assert str(recorded) == hypothesis_id, (
            f"Expected the action to name hypothesis {hypothesis_id}, got {recorded}."
        )

        return True

    return assertion


def _the_action_row_changed(conn: psycopg.Connection,
                            incident_id: str,
                            subject: str) -> Assertion[object]:
    """What the column holds, asked of the table directly.

    The column rather than the model, because the two failed differently and
    only one of them was visible: every read here selects `subject` and every
    write left it NULL, so a model populated from the row agreed with the row
    perfectly and both were empty.
    """
    def assertion(_result: object) -> bool:
        _, _, _, _, recorded = _the_only_action_row(conn, incident_id)

        assert recorded == subject, (
            f"Expected the action to have changed {subject}, got {recorded}."
        )

        return True

    return assertion


def _the_action_read_back_changed(conn: psycopg.Connection,
                                  incident_id: str,
                                  subject: str) -> Assertion[object]:
    """The same fact through the repository's own read.

    Both, because this is the one a caller sees. `composing.py` discards an
    attempt whose `subject` is empty, so a column written and not mapped back
    onto the model would leave long-term memory exactly as empty as a column
    never written at all.
    """
    def assertion(_result: object) -> bool:
        read_back = taken_actions.get_by_incident(conn, incident_id)

        assert len(read_back) == 1, (
            f"Expected exactly one action, got {len(read_back)}."
        )
        assert read_back[0].subject == subject, (
            f"Expected the action read back to name {subject}, "
            f"got {read_back[0].subject}."
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
                (incident_id,)
            )
            named = {str(row[0]) for row in cursor.fetchall()}

        assert named == candidates, (
            f"Expected the two actions to name {candidates}, got {named}."
        )

        return True

    return assertion


def _the_only_action_row(conn: psycopg.Connection,
                         incident_id: str) -> tuple[Any, Any, Any, Any, Any]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT type, outcome, undo_descriptor, hypothesis_id, subject "
            "FROM action WHERE incident_id = %s",
            (incident_id,)
        )
        rows = cursor.fetchall()

    assert len(rows) == 1, f"Expected exactly one action row, got {len(rows)}."

    return rows[0]


def _the_actions_read_back_are(conn: psycopg.Connection,
                               incident_id: str,
                               outcomes: list[str]) -> Assertion[Any]:
    """The outcomes of an incident's actions, in the order they come back.

    Order is the claim: a walk's actions are a sequence - tried, undone, tried
    again - and read back in any other order they describe a different
    incident.
    """
    def assertion(_result: Any) -> bool:
        found = [taken.outcome for taken in taken_actions.get_by_incident(conn, incident_id)]

        if found != outcomes:
            raise AssertionError(f"Expected outcomes {outcomes}, got {found}.")

        return True

    return assertion
