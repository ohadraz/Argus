from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    the_answer_was,
)
from core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    ActionProgress,
    ActionType,
    Alert,
    AlreadyClaimed,
    ClaimAnswer,
    Claimed,
    DeploymentRollbackUndo,
    FailureMode,
    FlagUndo,
    Hypothesis,
    Planned,
    SubjectOpen,
    TakenAction,
    UndoDescriptor,
    Undone,
    UnreadVerdict,
    Verdict,
)
from incident_record.repository import hypotheses, incidents, taken_actions
from incident_record.repository.taken_actions import NoLongerOpen
from postgres import connect_from_env
from psycopg import sql

from incident_record_test.framework import no_column_is_empty, written_and_rolled_back
from incident_record_test.framework.builders import an_incident_created_for

SOME_INSTANT = datetime(2026, 10, 26, 18, 4, 49, 35000, tzinfo=UTC)
DONT_CARE_INSTANT = datetime(2026, 10, 11, 23, 38, tzinfo=UTC)
# The platform's own clock, read before the state a plan was worked out from.
SOME_MOMENT_ITS_STATE_WAS_READ = datetime(2026, 11, 18, 9, 30, 12, tzinfo=UTC)
SOME_MOMENT_ARGUS_WROTE = SOME_MOMENT_ITS_STATE_WAS_READ + timedelta(seconds=3)
SOME_ENTRY_IT_WAS_ON = 2
# A rollback worked out and not yet made: the entry it returns to chosen, and
# no moment to date a write by.
SOME_ROLLBACK_PLAN = DeploymentRollbackUndo(
    application="io-shop",
    was_on_history_id=SOME_ENTRY_IT_WAS_ON,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    rolled_back_to_revision="544cef36a8eaf45c5b030c3d5c21473d8176cef3",
    rolled_back_to_history_id=SOME_ENTRY_IT_WAS_ON - 1,
    was_syncing_itself=True
)
# The plan as the claim keeps it: the rollback, and when the platform said what
# it was worked out from.
SOME_PLANNED_ROLLBACK = Planned(descriptor=SOME_ROLLBACK_PLAN, since=SOME_MOMENT_ITS_STATE_WAS_READ)
# What the write returned for it: the plan, dated by the platform.
THE_ROLLBACK_AS_MADE = SOME_ROLLBACK_PLAN.model_copy(
    update={"written_at": SOME_MOMENT_ARGUS_WROTE}
)
# The walk's clock when it said the change was made - what the row dates
# the change by, as the announcement does.
SOME_MOMENT_IT_WAS_ANNOUNCED = SOME_MOMENT_ARGUS_WROTE + timedelta(seconds=1)
# What the watch found that left a change owing its put-back, in its words.
SOME_FINDING = "the rule that fired was still firing when the time it allows ran out"
# The action's column a run's settle or a resolution sets, and nothing else.
SET_BY_A_SETTLE_OR_A_RESOLUTION = "open_until"


@pytest.mark.integration
def test_an_action_is_claimed_at_the_instant_its_claim_is_handed() -> None:
    # On the walk's clock, which dates everything else in the incident - a
    # replay's simulated one included - rather than on the database's, which
    # dates nothing else.
    some_alert = Alert(service="io-shop", alert_name="HighLatency")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_read_back_was_claimed_at = partial(_the_action_read_back_was_claimed_at, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=SOME_INSTANT
                )
            ) \
            .then(
                the_action_read_back_was_claimed_at(incident_id, SOME_INSTANT)
            )


@pytest.mark.integration
def test_a_claim_answers_with_the_id_of_the_row_it_wrote() -> None:
    # The id every write the action makes is marked with, so the platform's
    # object names the row that says what was done to it. Answered by the
    # claim itself, because it is the write that made the row.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _the_id_of_the_row_claimed_for(conn, incident_id, hypothesis_id)
            )


@pytest.mark.integration
def test_a_candidate_already_claimed_is_answered_with_no_row() -> None:
    # The row is the earlier attempt's, and so is its id: a second claim
    # handed it would mark this attempt's writes as that one's. Answered as
    # already claimed while that row is still claimed - an open change on the
    # very subject this claim names: the candidate's own claim is checked
    # first, so a walk resumed on its candidate is never told its own change
    # stands in the way.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        def claimed() -> ClaimAnswer:
            return taken_actions.claim(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                action_type="roll-back-deployment",
                subject="io-shop",
                at=DONT_CARE_INSTANT
            )

        Scenario() \
            .given(
                calling(claimed)
            ) \
            .when(
                claimed
            ) \
            .then(
                the_answer_was(AlreadyClaimed())
            )


@pytest.mark.integration
def test_a_claim_keeps_the_plan_it_was_handed_and_when_its_state_was_read() -> None:
    # Written before anything in the estate moves, because the row this table
    # exists for is one a worker stopped after writing. A resumed walk asks the
    # estate whether it is as the plan found it, as the plan asked for under
    # this claim's mark, or neither - and it can only ask that of a plan the
    # claim kept, dated by when the platform said what it held.
    #
    # Both reads: the one a resumed walk makes of its candidate, and the one
    # every reader of the incident makes.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                )
            ) \
            .then(all_of(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id,
                                             SOME_PLANNED_ROLLBACK),
                _the_plans_read_back_are(conn, incident_id, [SOME_PLANNED_ROLLBACK])
            ))


@pytest.mark.integration
@pytest.mark.parametrize("column", ["plan", "since"])
def test_the_table_refuses_half_a_plan(column: str) -> None:
    # A plan and the moment its state was read are one fact in two columns,
    # and the table holds them to it rather than every writer: a plan nobody
    # can date cannot be asked whether anything landed after it, and a moment
    # with no plan dates nothing. Either half emptied alone is refused.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                )
            ) \
            .when(attempting(
                lambda: _emptying(conn, incident_id, column)
            )) \
            .then(
                an_error_was_raised(psycopg.errors.CheckViolation)
            )


@pytest.mark.integration
def test_a_claim_with_a_plan_says_nothing_of_argus_is_out_there_yet() -> None:
    # The plan is what the write will compare against; the undo descriptor is
    # something of Argus's out in the estate. Written at the claim, a
    # withdrawal's unwinding would put back a change that was never made, and
    # every reader asking whether a change was left would be told one was.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                )
            ) \
            .then(all_of(
                _the_undo_read_back_is(conn, incident_id, None),
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.CLAIMED])
            ))


@pytest.mark.integration
def test_an_action_with_nothing_to_plan_is_claimed_without_a_plan() -> None:
    # A restart and a discard leave nothing to compare the estate with and no
    # moment it was read at. Their claim says so rather than holding a plan
    # nobody worked out.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="restart-service",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id, None)
            )


@pytest.mark.integration
def test_a_second_claim_on_a_candidate_leaves_the_first_claims_plan() -> None:
    # The plan belongs to the claim that holds the candidate. A later attempt
    # refused the candidate worked its plan out from an estate that may have
    # moved since; written over the first, it would have the first attempt's
    # resume compare the estate with something that attempt never planned.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    some_later_plan = SOME_ROLLBACK_PLAN.model_copy(
        update={"was_on_history_id": SOME_ENTRY_IT_WAS_ON + 1,
                "rolled_back_to_history_id": SOME_ENTRY_IT_WAS_ON}
    )

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                ))
            ) \
            .when(
                lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT + timedelta(minutes=1),
                    planned=Planned(descriptor=some_later_plan,
                                    since=SOME_MOMENT_ITS_STATE_WAS_READ + timedelta(minutes=1))
                )
            ) \
            .then(all_of(
                the_answer_was(AlreadyClaimed()),
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id,
                                             SOME_PLANNED_ROLLBACK)
            ))


@pytest.mark.integration
def test_a_change_made_leaves_the_plan_its_claim_kept() -> None:
    # The change made writes what the write returned beside the plan, never
    # over it: a resumed walk finding the row performed still asks whether the
    # estate is as Argus left it, and the plan is half of what it compares.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                )
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=THE_ROLLBACK_AS_MADE
                )
            ) \
            .then(all_of(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id,
                                             SOME_PLANNED_ROLLBACK),
                _the_undo_read_back_is(conn, incident_id, THE_ROLLBACK_AS_MADE)
            ))


@pytest.mark.integration
def test_a_completed_action_leaves_the_plan_its_claim_kept() -> None:
    # The attempt's whole account is written over the progress and the
    # descriptor, and still not over the plan: what Argus meant to do is a
    # fact of the claim, and no later word about the attempt changes it.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    at=DONT_CARE_INSTANT,
                    planned=SOME_PLANNED_ROLLBACK
                )
            ) \
            .when(
                lambda: taken_actions.complete(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    outcome=Verdict.REFUTED,
                    undo_descriptor=THE_ROLLBACK_AS_MADE,
                    left_behind_known=True,
                    undone=Undone.RESTORED
                )
            ) \
            .then(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id,
                                             SOME_PLANNED_ROLLBACK)
            )


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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_says = partial(_the_action_row_says, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    outcome=Verdict.CONFIRMED,
                    undo_descriptor=some_undo_descriptor,
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_carries = partial(_the_action_row_carries, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    outcome=Verdict.ESCALATED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
                )
            ) \
            .then(
                the_action_row_carries(incident_id, None)
            )


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_a_completed_action_says_whether_it_was_performed(performed: bool,
                                                          progress: ActionProgress) -> None:
    # What says the candidate was tried where nothing was measured: a person's
    # ending stops a test before the write and during the wait alike, and no
    # verdict tells the two apart.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [progress])
            )


@pytest.mark.integration
@pytest.mark.parametrize("left_behind_known", [True, False], ids=["known", "not-known"])
def test_a_completed_action_says_whether_what_it_left_is_known(
        left_behind_known: bool) -> None:
    # Two refusals that changed nothing anybody recorded, and only one of them
    # may be written up as having changed nothing: the tier that said it asked
    # for no change, against the one whose change request's answer was lost.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .when(
                lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=dont_care_hypothesis_id,
                    action_type="roll-back-deployment",
                    subject="io-shop",
                    outcome=Verdict.ESCALATED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=False,
                    left_behind_known=left_behind_known
                )
            ) \
            .then(
                _what_it_left_is_read_back_as_known(conn, incident_id, left_behind_known)
            )


@pytest.mark.integration
@pytest.mark.parametrize("undone", [Undone.RESTORED, Undone.LEFT_AS_FOUND, None],
                         ids=["restored", "left-as-found", "no-undo"])
def test_a_completed_action_says_what_its_own_putting_back_did(
        undone: Undone | None) -> None:
    # A refuted change restored, one left as somebody else had since set it, and
    # one nothing attempted to put back: the cleanup after the incident passes
    # over the first two and puts back the third, so the row must tell them apart.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_flag = "kuki-flag"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    subject=some_flag,
                    outcome=Verdict.REFUTED,
                    undo_descriptor=FlagUndo(flag=some_flag, was_enabled=True),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True,
                    undone=undone
                )
            ) \
            .then(
                _what_was_undone_is_read_back_as(conn, incident_id, undone)
            )


@pytest.mark.integration
def test_what_the_cleanup_did_with_a_change_is_kept_on_its_row() -> None:
    # The cleanup after a withdrawn or failed incident puts changes back too,
    # and the walk page shows a change by its row. Said only on the timeline, a
    # change a withdrawal put back read on the page as the step that stopped.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                dont_care_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .given(
                action_id := _a_change_recorded(conn, incident_id, dont_care_hypothesis_id)
            ) \
            .when(
                lambda: taken_actions.record_undone(conn, action_id, Undone.RESTORED)
            ) \
            .then(
                _what_was_undone_is_read_back_as(conn, incident_id, Undone.RESTORED)
            )


@pytest.mark.integration
def test_an_action_only_claimed_is_not_known_to_have_left_nothing() -> None:
    # A worker that stopped after its claim may have made the change, so the
    # row says nothing is known until something more is written.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    subject="dont-care-flag",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _what_it_left_is_read_back_as_known(conn, incident_id, False)
            )


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_the_action_claimed_for_a_candidate_says_how_far_it_got(
        performed: bool, progress: ActionProgress) -> None:
    # The other read of the row - the one a resumed walk makes - maps the column
    # back too.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
            ) \
            .given(
                some_hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .given(
                calling(lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=some_hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                ))
            ) \
            .when(
                lambda: taken_actions.get_action_for_hypothesis(conn, incident_id,
                                                                some_hypothesis_id)
            ) \
            .then(
                _it_progressed_to(progress)
            )


@pytest.mark.integration
def test_an_action_only_claimed_is_known_as_claimed() -> None:
    # The state a row is in from the claim until anything else is known about
    # it - the action about to be taken, or taken by a worker that stopped
    # before saying so.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    subject="dont-care-flag",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.CLAIMED])
            )


@pytest.mark.integration
def test_a_change_made_is_recorded_with_what_puts_it_back_before_any_verdict() -> None:
    # Written the moment the change is made, before the wait. A worker that
    # dies during the wait leaves a row saying the change was made and how to
    # put it back - which is what a withdrawal, or a failed run's unwinding,
    # reads through this same read.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_undo_descriptor = FlagUndo(flag="monthly-spend-feature", was_enabled=True)

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=some_undo_descriptor
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PERFORMED]),
                _the_undo_read_back_is(conn, incident_id, some_undo_descriptor),
                _the_outcome_read_back_is_absent(conn, incident_id)
            ))


@pytest.mark.integration
@pytest.mark.parametrize(("performed", "progress"),
                         [(True, ActionProgress.PERFORMED),
                          (False, ActionProgress.NOT_PERFORMED)],
                         ids=["performed", "never-performed"])
def test_an_action_already_completed_is_not_moved_back(performed: bool,
                                                       progress: ActionProgress) -> None:
    # Only a claim moves on. A completion is the whole account of the
    # attempt, and a later write about a claim - a resumed walk that could
    # not tell what happened - must not overwrite what the attempt itself
    # recorded.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    outcome=Verdict.STOPPED,
                    undo_descriptor=None,
                    at=DONT_CARE_INSTANT,
                    performed=performed,
                    left_behind_known=True
                ))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.UNKNOWN,
                    undo_descriptor=None
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [progress])
            )


@pytest.mark.integration
def test_an_action_nobody_can_account_for_stays_unaccounted_for() -> None:
    # Unknown is final. A resumed walk that finds it escalates without asking
    # again, so nothing may later turn it into a claim's answer it never got.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)
        taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                            action_type="revert-feature-flag", subject="dont-care-flag",
                            at=DONT_CARE_INSTANT)

        Scenario() \
            .given(
                calling(lambda: taken_actions.advance(conn, incident_id,
                                                      hypothesis_id=hypothesis_id,
                                                      to=ActionProgress.UNKNOWN,
                                                      undo_descriptor=None))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=FlagUndo(flag="dont-care-flag", was_enabled=True)
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.UNKNOWN])
            )


# The flags the settling case's four actions are on: one each, since one
# subject holds one open change at a time.
A_FLAG_STILL_CLAIMED = "first-flag"
A_FLAG_SWITCHED = "second-flag"
A_FLAG_NEVER_SWITCHED = "third-flag"
ANOTHER_INCIDENT_S_FLAG = "fourth-flag"


@pytest.mark.integration
def test_settling_an_incidents_claims_leaves_every_row_that_moved_on_alone() -> None:
    # Where no walk will write the incident's rows again. A claim still open
    # there will never be answered, so it becomes unknown; every row that
    # already says more keeps what it says - and another incident's claim is
    # that incident's.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        another_incident_id = an_incident_created_for(conn, some_alert)
        still_claimed = a_hypothesis_recorded_for(incident_id, subject="first", rank=1)
        performed = a_hypothesis_recorded_for(incident_id, subject="second", rank=2)
        never_performed = a_hypothesis_recorded_for(incident_id, subject="third", rank=3)
        anothers = a_hypothesis_recorded_for(another_incident_id)

        # Each on a flag of its own: one subject holds one open change at a time.
        def four_actions_got_as_far_as_they_did() -> None:
            for candidate, flag, at in ((still_claimed, A_FLAG_STILL_CLAIMED, SOME_INSTANT),
                                        (performed, A_FLAG_SWITCHED,
                                         SOME_INSTANT + timedelta(minutes=1))):
                taken_actions.claim(conn, incident_id, hypothesis_id=candidate,
                                    action_type="revert-feature-flag",
                                    subject=flag, at=at)
            taken_actions.advance(conn, incident_id, hypothesis_id=performed,
                                  to=ActionProgress.PERFORMED, undo_descriptor=None)
            taken_actions.record(conn, incident_id, hypothesis_id=never_performed,
                                 action_type="revert-feature-flag",
                                 subject=A_FLAG_NEVER_SWITCHED,
                                 outcome=Verdict.PLATFORM_UNREACHABLE, undo_descriptor=None,
                                 at=SOME_INSTANT + timedelta(minutes=2), performed=False,
                                 left_behind_known=True)
            taken_actions.claim(conn, another_incident_id, hypothesis_id=anothers,
                                action_type="revert-feature-flag",
                                subject=ANOTHER_INCIDENT_S_FLAG, at=DONT_CARE_INSTANT)

        Scenario() \
            .given(
                calling(four_actions_got_as_far_as_they_did)
            ) \
            .when(
                lambda: taken_actions.settle_claims(conn, incident_id)
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id,
                                           [ActionProgress.UNKNOWN,
                                            ActionProgress.PERFORMED,
                                            ActionProgress.NOT_PERFORMED]),
                _the_progress_read_back_is(conn, another_incident_id,
                                           [ActionProgress.CLAIMED])
            ))


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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)
        the_action_read_back_changed = partial(_the_action_read_back_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    outcome=Verdict.CONFIRMED,
                    undo_descriptor=FlagUndo(
                        flag=the_flag_that_was_changed, was_enabled=True
                    ),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_changed = partial(_the_action_row_changed, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    subject=the_flag_that_was_changed,
                    at=DONT_CARE_INSTANT
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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_action_row_names = partial(_the_action_row_names, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, some_alert)
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
                    outcome=Verdict.REFUTED,
                    undo_descriptor=FlagUndo(flag="monthly-spend-feature", was_enabled=False),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True
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
    # on its continuing to. The first was refuted and put back, so its change no
    # longer stands in the way of the second.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_contested_flag = "monthly-spend-feature"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        each_action_names_its_own_candidate = partial(
            _each_action_names_its_own_candidate, conn
        )

        incident_id = an_incident_created_for(conn, some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject=the_contested_flag, rank=2)

        def an_action_is_taken_for_each() -> None:
            for candidate, outcome, undone in ((first, Verdict.REFUTED, Undone.RESTORED),
                                               (second, Verdict.CONFIRMED, None)):
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject=the_contested_flag,
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag=the_contested_flag, was_enabled=True),
                    at=DONT_CARE_INSTANT,
                    left_behind_known=True,
                    undone=undone
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
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_actions_read_back_are = partial(_the_actions_read_back_are, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        first = a_hypothesis_recorded_for(incident_id, subject="first", rank=1)
        second = a_hypothesis_recorded_for(incident_id, subject="second", rank=2)

        # Tried, put back, and tried again: the first change no longer stands
        # when the second is claimed.
        def two_actions_are_taken() -> None:
            for candidate, outcome, undone, at in (
                    (first, Verdict.REFUTED, Undone.RESTORED, SOME_INSTANT),
                    (second, Verdict.CONFIRMED, None, SOME_INSTANT + timedelta(minutes=4))):
                taken_actions.record(
                    conn,
                    incident_id,
                    hypothesis_id=candidate,
                    action_type="revert-feature-flag",
                    subject="dont-care",
                    outcome=outcome,
                    undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True),
                    at=at,
                    left_behind_known=True,
                    undone=undone
                )

        Scenario() \
            .when(
                two_actions_are_taken
            ) \
            .then(
                the_actions_read_back_are(incident_id, ["refuted", "confirmed"])
            )


@pytest.mark.integration
def test_an_outcome_no_verdict_spells_comes_back_unread_rather_than_absent() -> None:
    # The read every other reader comes through, asked about the row none of
    # them can spell. Absence is the state it must not collapse into: a claim
    # with no outcome means the worker died between acting and recording, and
    # it is the one row whose change may be out there unmeasured - so reading
    # a finished action as that one sends the walk to ask the provider about a
    # verdict that was already reached.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    a_verdict_this_version_cannot_spell = "dissolved"

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        an_older_versions_verdict_on = partial(_an_older_versions_verdict_on, conn)

        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="monthly-spend-feature",
                    at=DONT_CARE_INSTANT
                )
            ) \
            .given(
                an_older_versions_verdict_on(
                    incident_id, a_verdict_this_version_cannot_spell
                )
            ) \
            .when(
                lambda: taken_actions.get_action_for_hypothesis(
                    conn, incident_id, hypothesis_id
                )
            ) \
            .then(
                _the_outcome_read_back_is(
                    UnreadVerdict(a_verdict_this_version_cannot_spell)
                )
            )


@pytest.mark.integration
def test_a_completed_action_leaves_no_column_of_its_row_empty() -> None:
    # The other half of the written-columns guard, and the half that can see
    # what a static reading cannot: a writer that names a column and is never
    # called, and one that is called and puts NULL there, both satisfy a guard
    # that only asks whether a writer exists in the source.
    #
    # One action with everything an action can have, written the way the walk
    # writes it: a claim with its plan, a candidate and a subject; the change
    # made, with what puts it back and when the walk recorded it, on its clock;
    # owing its put-back once the watch refuted it, with why; and completed
    # with the verdict and the walk's own putting back of it. A row
    # legitimately lacking one of those is a different case with its own test
    # above; this asks whether the complete case reaches the table complete.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    the_flag_that_was_changed = "monthly-spend-feature"
    some_plan = FlagUndo(flag=the_flag_that_was_changed, was_enabled=True)
    some_change_made = some_plan.model_copy(update={"written_at": SOME_MOMENT_ARGUS_WROTE})

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        def claimed_made_and_owing_its_put_back() -> None:
            taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                                action_type="revert-feature-flag",
                                subject=the_flag_that_was_changed, at=DONT_CARE_INSTANT,
                                planned=Planned(descriptor=some_plan,
                                                since=SOME_MOMENT_ITS_STATE_WAS_READ))
            taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                                  to=ActionProgress.PERFORMED,
                                  undo_descriptor=some_change_made,
                                  performed_at=SOME_MOMENT_IT_WAS_ANNOUNCED)
            taken_actions.owe_a_put_back(conn, incident_id, hypothesis_id=hypothesis_id,
                                         because=SOME_FINDING)

        Scenario() \
            .given(
                calling(claimed_made_and_owing_its_put_back)
            ) \
            .when(
                lambda: taken_actions.complete(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    outcome=Verdict.REFUTED,
                    undo_descriptor=some_change_made,
                    left_behind_known=True,
                    undone=Undone.RESTORED
                )
            ) \
            .then(
                # `open_until` is the one column a complete action leaves empty,
                # and rightly: it is set by a run's settle or its incident's
                # resolution, neither of which is the walk's writing of an
                # action. Its writers are pinned by the tests of those two.
                no_column_is_empty(conn, "action", "incident_id", incident_id,
                                   except_for=[SET_BY_A_SETTLE_OR_A_RESOLUTION])
            )


@pytest.mark.integration
def test_a_claim_rolled_back_by_its_caller_leaves_the_candidate_unclaimed() -> None:
    # Committing is the caller's. A claim that committed on its own would stand
    # after its caller rolled back, and every later walk would be refused the
    # candidate, for an action nobody took.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)

        Scenario() \
            .given(
                incident_id := an_incident_created_for(conn, dont_care_alert)
            ) \
            .given(
                hypothesis_id := a_hypothesis_recorded_for(incident_id)
            ) \
            .given(
                calling(written_and_rolled_back(conn, lambda: taken_actions.claim(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    action_type="revert-feature-flag",
                    subject="dont-care-flag",
                    at=DONT_CARE_INSTANT
                )))
            ) \
            .when(
                lambda: taken_actions.get_action_for_hypothesis(conn, incident_id, hypothesis_id)
            ) \
            .then(
                the_answer_was(None)
            )


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
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
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


def _what_it_left_is_read_back_as_known(conn: psycopg.Connection,
                                        incident_id: str,
                                        expected: bool) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        read_back = [action.left_behind_known
                     for action in taken_actions.get_by_incident(conn, incident_id)]

        if read_back != [expected]:
            raise AssertionError(
                f"Expected one action whose left_behind_known reads [{expected}], "
                f"and the incident's actions read {read_back}"
            )

        return True

    return assertion


def _a_change_recorded(conn: psycopg.Connection,
                       incident_id: str,
                       hypothesis_id: str) -> str:
    """A flag change a withdrawn walk made and stopped before judging, and the
    id of its row - which is how the cleanup holds it."""
    some_flag = "kuki-flag"
    taken_actions.record(
        conn,
        incident_id,
        hypothesis_id=hypothesis_id,
        action_type="revert-feature-flag",
        subject=some_flag,
        outcome=Verdict.STOPPED,
        undo_descriptor=FlagUndo(flag=some_flag, was_enabled=True),
        at=DONT_CARE_INSTANT,
        left_behind_known=True
    )

    return taken_actions.get_by_incident(conn, incident_id)[0].id


def _what_was_undone_is_read_back_as(conn: psycopg.Connection,
                                     incident_id: str,
                                     expected: Undone | None) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        read_back = [action.undone
                     for action in taken_actions.get_by_incident(conn, incident_id)]

        if read_back != [expected]:
            raise AssertionError(
                f"Expected one action whose undone reads [{expected}], "
                f"and the incident's actions read {read_back}"
            )

        return True

    return assertion


def _the_progress_read_back_is(conn: psycopg.Connection,
                               incident_id: str,
                               expected: list[ActionProgress]) -> Assertion[object]:
    """How far each of the incident's actions got, in the order they were taken."""
    def assertion(_result: object) -> bool:
        found = [action.progress for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != expected:
            raise AssertionError(f"Expected the actions read back as {expected}, got {found}")

        return True

    return assertion


def _it_progressed_to(expected: ActionProgress) -> Assertion[TakenAction | None]:
    def assertion(action: TakenAction | None) -> bool:
        found = action.progress if action is not None else None
        if found is not expected:
            raise AssertionError(f"Expected the action read back as [{expected}], "
                                 f"got [{found}].")

        return True

    return assertion


def _the_undo_read_back_is(conn: psycopg.Connection,
                           incident_id: str,
                           expected: UndoDescriptor | None) -> Assertion[object]:
    """What would put the change back, through the read an unwinding makes."""
    def assertion(_result: object) -> bool:
        found = [action.undo_descriptor
                 for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [expected]:
            raise AssertionError(f"Expected one action read back carrying [{expected}], "
                                 f"got {found}")

        return True

    return assertion


def _emptying(conn: psycopg.Connection, incident_id: str, column: str) -> None:
    """Empties one column of the incident's actions, as no writer of this
    module ever would - inside a savepoint, so the refusal leaves the
    connection usable."""
    with conn.transaction():
        conn.execute(
            sql.SQL("UPDATE action SET {} = NULL WHERE incident_id = %s").format(
                sql.Identifier(column)
            ),
            (incident_id,)
        )


def _the_claim_read_back_planned(conn: psycopg.Connection,
                                 incident_id: str,
                                 hypothesis_id: str,
                                 planned: Planned[Any] | None) -> Assertion[object]:
    """What the candidate's claim planned, through the read a resumed walk makes."""
    def assertion(_result: object) -> bool:
        action = taken_actions.get_action_for_hypothesis(conn, incident_id, hypothesis_id)

        if action is None:
            raise AssertionError(
                f"Expected the claim read back planning [{planned!r}], and the "
                f"candidate has no row."
            )

        if action.planned != planned:
            raise AssertionError(
                f"Expected the claim read back planning [{planned!r}], got "
                f"[{action.planned!r}]."
            )

        return True

    return assertion


def _the_plans_read_back_are(conn: psycopg.Connection,
                             incident_id: str,
                             expected: list[Planned[Any] | None]) -> Assertion[object]:
    """What each of the incident's actions planned, through the read every
    reader of the incident makes."""
    def assertion(_result: object) -> bool:
        found = [action.planned for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != expected:
            raise AssertionError(
                f"Expected the incident's actions read back planning {expected}, "
                f"got {found}"
            )

        return True

    return assertion


def _the_outcome_read_back_is_absent(conn: psycopg.Connection,
                                     incident_id: str) -> Assertion[object]:
    """No verdict yet: the change being made is not what came of it."""
    def assertion(_result: object) -> bool:
        found = [action.outcome for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [None]:
            raise AssertionError(f"Expected one action read back with no outcome, got {found}")

        return True

    return assertion


def _the_action_read_back_was_claimed_at(conn: psycopg.Connection,
                                       incident_id: str,
                                       instant: datetime) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        read_back = taken_actions.get_by_incident(conn, incident_id)

        if [taken.taken_at for taken in read_back] != [instant]:
            raise AssertionError(f"Expected one action claimed at [{instant}], got "
                                 f"{[str(taken.taken_at) for taken in read_back]}")

        return True

    return assertion


def _the_id_of_the_row_claimed_for(conn: psycopg.Connection,
                                   incident_id: str,
                                   hypothesis_id: str) -> Assertion[ClaimAnswer]:
    """The answer is claimed, with the id of the one row the candidate has,
    read back."""
    def assertion(answered: ClaimAnswer) -> bool:
        row = taken_actions.get_action_for_hypothesis(conn, incident_id, hypothesis_id)

        if row is None:
            raise AssertionError(
                f"Expected the claim answered with its row's id, and no row was "
                f"written; it answered [{answered}]."
            )

        if answered != Claimed(action_id=row.id):
            raise AssertionError(
                f"Expected the claim answered with its row's id [{row.id}], got "
                f"[{answered}]."
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
            raise AssertionError(f"Expected outcomes {outcomes}, got {found}")

        return True

    return assertion


def _an_older_versions_verdict_on(conn: psycopg.Connection,
                                  incident_id: str,
                                  spelling: str) -> None:
    """One finished action whose outcome is spelled in a way this version does
    not know.

    Written in SQL, and the only thing here that is. Everything a writer can
    produce is produced by the real writer - the claim above this is
    `taken_actions.claim` for exactly that reason - because a test that seeds
    the store by hand proves the reader understands a shape the test itself
    invented, which is how a column read by two modules went its whole life
    unwritten.

    This row is the exception, and it is the exception because production
    cannot make one: `complete` takes a `Verdict`, so every spelling Argus
    writes is a spelling Argus reads. A row that disagrees comes from a version
    that is gone - a rename, an older deploy mid-migration - and the inability
    to write one is the behaviour under test, not a corner the seeding cuts.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE action SET outcome = %s WHERE incident_id = %s",
            (spelling, incident_id)
        )
    conn.commit()


def _the_outcome_read_back_is(expected: Verdict | UnreadVerdict | None
                              ) -> Assertion[TakenAction | None]:
    """What the row's outcome is, as a value and as a type.

    Both, because `UnreadVerdict("refuted")` equals `Verdict.REFUTED` and is
    not one - and because the type is the whole distinction here: read back as
    `None`, an unreadable verdict is an action nobody finished, and the
    resuming walk goes and asks the provider whether a change it already has a
    verdict for ever landed.
    """
    def assertion(action: TakenAction | None) -> bool:
        if action is None:
            raise AssertionError(
                f"Expected an action whose outcome reads back as [{expected!r}], "
                f"got no row at all."
            )

        if action.outcome != expected or type(action.outcome) is not type(expected):
            raise AssertionError(
                f"Expected the outcome to read back as [{expected!r}], got "
                f"[{action.outcome!r}]."
            )

        return True

    return assertion


@pytest.mark.integration
def test_a_change_made_is_recorded_with_the_moment_the_walk_said_it_was_made() -> None:
    # On the walk's clock, as the announcement is: what a resumed walk watches
    # the change afresh from, against minutes the walk's own clock dates.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_claim(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=THE_ROLLBACK_AS_MADE,
                    performed_at=SOME_MOMENT_IT_WAS_ANNOUNCED
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PERFORMED]),
                _it_was_made_at(conn, incident_id, SOME_MOMENT_IT_WAS_ANNOUNCED)
            ))


@pytest.mark.integration
def test_a_change_a_resumed_walk_found_made_is_recorded_with_no_moment() -> None:
    # A resumed walk that learns a dead worker's change landed was not there
    # when it was made, and its own clock now is no stand-in: absent says so.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_claim(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.PERFORMED,
                    undo_descriptor=None
                )
            ) \
            .then(
                _it_was_made_at(conn, incident_id, None)
            )


@pytest.mark.integration
def test_a_change_the_watch_refuted_comes_to_owe_its_put_back_with_why() -> None:
    # Written before the put-back is attempted, so a worker that dies between
    # the two leaves a row saying the change is owed back and why - which a
    # resumed walk puts it back on without watching it again. No verdict yet:
    # that is the put-back's to complete.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_made(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.owe_a_put_back(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    because=SOME_FINDING
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PUTTING_BACK]),
                _it_owes_its_put_back_because(conn, incident_id, SOME_FINDING),
                _the_undo_read_back_is(conn, incident_id, THE_ROLLBACK_AS_MADE),
                _it_was_made_at(conn, incident_id, SOME_MOMENT_IT_WAS_ANNOUNCED),
                _the_outcome_read_back_is_absent(conn, incident_id)
            ))


# How far an action got before a put-back is owed, built before the case that
# names them, since its parameters are read as the module loads.
def _a_claim(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    """A rollback claimed on its plan, and nothing said since."""
    taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                        action_type="roll-back-deployment", subject="io-shop",
                        at=DONT_CARE_INSTANT, planned=SOME_PLANNED_ROLLBACK)


def _a_claim_nobody_answered(conn: psycopg.Connection,
                             incident_id: str,
                             hypothesis_id: str) -> None:
    _a_claim(conn, incident_id, hypothesis_id)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.UNKNOWN, undo_descriptor=None)


def _an_action_never_performed(conn: psycopg.Connection,
                               incident_id: str,
                               hypothesis_id: str) -> None:
    _a_claim(conn, incident_id, hypothesis_id)
    taken_actions.complete(conn, incident_id, hypothesis_id=hypothesis_id,
                           outcome=Verdict.PLATFORM_UNREACHABLE, undo_descriptor=None,
                           performed=False, left_behind_known=True)


def _an_action_completed(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    _a_change_made(conn, incident_id, hypothesis_id)
    taken_actions.complete(conn, incident_id, hypothesis_id=hypothesis_id,
                           outcome=Verdict.CONFIRMED, undo_descriptor=THE_ROLLBACK_AS_MADE,
                           left_behind_known=True)


@pytest.mark.integration
@pytest.mark.parametrize(("got_as_far_as", "stays"), [
    pytest.param(_a_claim, ActionProgress.CLAIMED, id="a-claim"),
    pytest.param(_a_claim_nobody_answered, ActionProgress.UNKNOWN, id="a-claim-nobody-answered"),
    pytest.param(_an_action_never_performed, ActionProgress.NOT_PERFORMED, id="never-performed"),
    pytest.param(_an_action_completed, ActionProgress.PERFORMED, id="already-completed")
])
def test_only_a_change_made_and_not_yet_completed_comes_to_owe_its_put_back(
        got_as_far_as: Callable[[psycopg.Connection, str, str], None],
        stays: ActionProgress) -> None:
    # A claim may never have changed anything, and a row that already says
    # more is the attempt's own account: a later write owing a put-back must
    # not overwrite either with something they never were.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: got_as_far_as(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.owe_a_put_back(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    because=SOME_FINDING
                )
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [stays])
            )


# A resumed walk's own plan, read a minute after the one a claim may carry.
THIS_WALK_S_PLAN = Planned(descriptor=SOME_ROLLBACK_PLAN,
                           since=SOME_MOMENT_ITS_STATE_WAS_READ + timedelta(minutes=1))


def _a_claim_with_no_plan(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    """A rollback claimed with no plan - its plan was refused - and nothing
    said since."""
    taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                        action_type="roll-back-deployment", subject="io-shop",
                        at=DONT_CARE_INSTANT, planned=None)


def _a_claim_with_no_plan_nobody_answered(conn: psycopg.Connection,
                                          incident_id: str,
                                          hypothesis_id: str) -> None:
    _a_claim_with_no_plan(conn, incident_id, hypothesis_id)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.UNKNOWN, undo_descriptor=None)


@pytest.mark.integration
def test_a_claim_written_with_no_plan_is_given_the_plan_a_resumed_walk_takes_it_on() -> None:
    # Written before the write, so the plan the write compares with lives on
    # the claim, as a walk that planned first writes it with the claim.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_claim_with_no_plan(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.plan_the_claim(conn, incident_id,
                                                     hypothesis_id=hypothesis_id,
                                                     planned=THIS_WALK_S_PLAN)
            ) \
            .then(all_of(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id, THIS_WALK_S_PLAN),
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.CLAIMED])
            ))


@pytest.mark.integration
@pytest.mark.parametrize(("got_as_far_as", "planned", "stays"), [
    pytest.param(_a_claim, SOME_PLANNED_ROLLBACK, ActionProgress.CLAIMED,
                 id="a-claim-carrying-a-plan"),
    pytest.param(_a_claim_with_no_plan_nobody_answered, None, ActionProgress.UNKNOWN,
                 id="a-claim-moved-on-with-no-plan")
])
def test_only_a_claim_still_carrying_no_plan_is_given_one(
        got_as_far_as: Callable[[psycopg.Connection, str, str], None],
        planned: Planned[Any] | None,
        stays: ActionProgress) -> None:
    # A plan already on a claim is the one its write compares with, and a row
    # past its claim says more than a plan: neither is written over.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: got_as_far_as(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.plan_the_claim(conn, incident_id,
                                                     hypothesis_id=hypothesis_id,
                                                     planned=THIS_WALK_S_PLAN)
            ) \
            .then(all_of(
                _the_claim_read_back_planned(conn, incident_id, hypothesis_id, planned),
                _the_progress_read_back_is(conn, incident_id, [stays])
            ))


@pytest.mark.integration
def test_an_action_owing_its_put_back_is_not_moved_back_by_an_advance() -> None:
    # Only a claim advances. A resumed walk's answer about a claim is never an
    # answer about a change already owed back.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_owing_its_put_back(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.advance(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    to=ActionProgress.UNKNOWN,
                    undo_descriptor=None
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PUTTING_BACK]),
                _the_undo_read_back_is(conn, incident_id, THE_ROLLBACK_AS_MADE)
            ))


@pytest.mark.integration
def test_a_put_back_that_never_ran_completes_the_action_still_owing_it() -> None:
    # A person ended the incident between the refutation and the put-back. The
    # verdict is the watch's and is recorded; the step stays where it was,
    # since it is what says the change was never put back - and so a
    # withdrawal's cleanup puts it back.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_owing_its_put_back(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.complete(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    outcome=Verdict.REFUTED,
                    undo_descriptor=THE_ROLLBACK_AS_MADE,
                    left_behind_known=True,
                    undone=None
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PUTTING_BACK]),
                _the_outcome_read_back_is_on(conn, incident_id, Verdict.REFUTED),
                _what_was_undone_is_read_back_as(conn, incident_id, None)
            ))


@pytest.mark.integration
@pytest.mark.parametrize(("undone", "verdict"), [
    pytest.param(Undone.RESTORED, Verdict.REFUTED, id="restored"),
    pytest.param(Undone.LEFT_AS_FOUND, Verdict.REFUTED, id="left-as-found"),
    pytest.param(Undone.LEFT_STANDING, Verdict.ESCALATED, id="left-standing"),
    pytest.param(Undone.NOT_ESTABLISHED, Verdict.ESCALATED, id="not-established")
])
def test_a_put_back_that_ran_completes_the_action_as_performed(undone: Undone,
                                                               verdict: Verdict) -> None:
    # Whatever the put-back found, it ran - so the row is the attempt's whole
    # account, as every completed change made is.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_owing_its_put_back(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.complete(
                    conn,
                    incident_id,
                    hypothesis_id=hypothesis_id,
                    outcome=verdict,
                    undo_descriptor=THE_ROLLBACK_AS_MADE,
                    left_behind_known=True,
                    undone=undone
                )
            ) \
            .then(all_of(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PERFORMED]),
                _what_was_undone_is_read_back_as(conn, incident_id, undone),
                _it_owes_its_put_back_because(conn, incident_id, SOME_FINDING)
            ))


@pytest.mark.integration
def test_settling_an_incidents_claims_leaves_an_action_owing_its_put_back_where_it_is() -> None:
    # A run lost between the refutation and the put-back leaves its row owing
    # the put-back, which says more than unknown: the change was made, and why
    # it is owed back is known.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_owing_its_put_back(conn, incident_id, hypothesis_id))
            ) \
            .when(
                lambda: taken_actions.settle_claims(conn, incident_id)
            ) \
            .then(
                _the_progress_read_back_is(conn, incident_id, [ActionProgress.PUTTING_BACK])
            )


@pytest.mark.integration
@pytest.mark.parametrize("column", ["put_back_because", "undo_descriptor"])
def test_the_table_refuses_an_action_owing_its_put_back_without_why_or_what_puts_it_back(
        column: str) -> None:
    # A change is owed back only once the watch refuted it, which it says why,
    # and only where there is something to put back: a row at that step
    # missing either is not one any writer here made.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, some_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _a_change_owing_its_put_back(conn, incident_id, hypothesis_id))
            ) \
            .when(attempting(
                lambda: _emptying(conn, incident_id, column)
            )) \
            .then(
                an_error_was_raised(psycopg.errors.CheckViolation)
            )


def _a_change_made(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    """A rollback claimed on its plan and made, dated on the walk's clock."""
    taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                        action_type="roll-back-deployment", subject="io-shop",
                        at=DONT_CARE_INSTANT, planned=SOME_PLANNED_ROLLBACK)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.PERFORMED, undo_descriptor=THE_ROLLBACK_AS_MADE,
                          performed_at=SOME_MOMENT_IT_WAS_ANNOUNCED)


def _a_change_owing_its_put_back(conn: psycopg.Connection,
                                 incident_id: str,
                                 hypothesis_id: str) -> None:
    """A rollback made and refuted, not yet put back."""
    _a_change_made(conn, incident_id, hypothesis_id)
    taken_actions.owe_a_put_back(conn, incident_id, hypothesis_id=hypothesis_id,
                                 because=SOME_FINDING)


def _it_was_made_at(conn: psycopg.Connection,
                    incident_id: str,
                    expected: datetime | None) -> Assertion[object]:
    """When the walk recorded the change made, on its clock, through the
    read every reader makes."""
    def assertion(_result: object) -> bool:
        found = [action.performed_at
                 for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [expected]:
            raise AssertionError(f"Expected one action read back as made at [{expected}], "
                                 f"got {found}")

        return True

    return assertion


def _it_owes_its_put_back_because(conn: psycopg.Connection,
                                  incident_id: str,
                                  expected: str) -> Assertion[object]:
    """Why the change is owed back, through the read a resumed walk makes."""
    def assertion(_result: object) -> bool:
        found = [action.put_back_because
                 for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [expected]:
            raise AssertionError(f"Expected one action read back owing its put-back because "
                                 f"[{expected}], got {found}")

        return True

    return assertion


def _the_outcome_read_back_is_on(conn: psycopg.Connection,
                                 incident_id: str,
                                 expected: Verdict) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        found = [action.outcome for action in taken_actions.get_by_incident(conn, incident_id)]

        if found != [expected]:
            raise AssertionError(f"Expected one action read back with the outcome "
                                 f"[{expected}], got {found}")

        return True

    return assertion


# ---------------------------------------------------------------------------
# One open change per subject, across incidents
# ---------------------------------------------------------------------------

# The flag two incidents both reach for, and the way back from switching it off.
THE_CONTESTED_FLAG = "kuki-flag"
THE_WAY_BACK = FlagUndo(flag=THE_CONTESTED_FLAG, was_enabled=True)
# The application the deployment kinds act on.
THE_CONTESTED_APPLICATION = "io-shop"
# When a run settled, or a person resolved its incident: the moment a change
# stops being open on its subject.
SOME_MOMENT_IT_STOPPED_BEING_OPEN = SOME_INSTANT + timedelta(hours=1)
# A later claim than every first one here.
A_LATER_INSTANT = SOME_INSTANT + timedelta(minutes=5)
# No incident holds a subject open: a later claim on it is claimed.
NOBODY = None


def _claimed(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                        action_type=REVERT_FEATURE_FLAG, subject=THE_CONTESTED_FLAG,
                        at=SOME_INSTANT)


def _performed(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    _claimed(conn, incident_id, hypothesis_id)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK)


def _putting_back(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    _performed(conn, incident_id, hypothesis_id)
    taken_actions.owe_a_put_back(conn, incident_id, hypothesis_id=hypothesis_id,
                                 because=SOME_FINDING)


def _unknown(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    _claimed(conn, incident_id, hypothesis_id)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.UNKNOWN, undo_descriptor=None)


def _completed(outcome: Verdict,
               undone: Undone | None,
               performed: bool = True,
               undo_descriptor: UndoDescriptor | None = THE_WAY_BACK,
               left_behind_known: bool = True
               ) -> Callable[[psycopg.Connection, str, str], None]:
    """The flag change completed with `outcome`, its put-back having come to
    `undone`."""
    def completed(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
        _claimed(conn, incident_id, hypothesis_id)
        taken_actions.complete(conn, incident_id, hypothesis_id=hypothesis_id,
                               outcome=outcome, undo_descriptor=undo_descriptor,
                               performed=performed, left_behind_known=left_behind_known,
                               undone=undone)

    return completed


def _settled_by_a_person(conn: psycopg.Connection, incident_id: str, hypothesis_id: str) -> None:
    """The change made and standing, and its incident ended by a person."""
    _performed(conn, incident_id, hypothesis_id)
    taken_actions.no_longer_open(conn, incident_id, SOME_MOMENT_IT_STOPPED_BEING_OPEN,
                                 which=NoLongerOpen.EVERY_ROW)


def _a_restart_nobody_answered(conn: psycopg.Connection,
                               incident_id: str,
                               hypothesis_id: str) -> None:
    """A restart claimed, and moved to unknown by a resumed walk."""
    _a_restart_claimed(conn, incident_id, hypothesis_id)
    taken_actions.advance(conn, incident_id, hypothesis_id=hypothesis_id,
                          to=ActionProgress.UNKNOWN, undo_descriptor=None)


def _a_restart_never_performed(conn: psycopg.Connection,
                               incident_id: str,
                               hypothesis_id: str) -> None:
    """A restart the platform never carried out, with nobody saying what it
    left: only that a restart has no way back makes it hold nothing."""
    nothing_to_put_back = None
    _a_restart_claimed(conn, incident_id, hypothesis_id)
    taken_actions.complete(conn, incident_id, hypothesis_id=hypothesis_id,
                           outcome=Verdict.PLATFORM_UNREACHABLE,
                           undo_descriptor=nothing_to_put_back, performed=False,
                           left_behind_known=False)


# Every way a change may still stand on its subject: in flight, made, owed
# back, unaccounted for, confirmed and left in place, left beside somebody's
# change, put back with nothing established, or never performed with
# something of it left behind - or with nothing said of what it left. Each
# with the kind and subject a later claim reaches for.
EVERY_CHANGE_STILL_OPEN = [
    pytest.param(_claimed, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="claimed"),
    pytest.param(_performed, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="performed"),
    pytest.param(_putting_back, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="putting-back"),
    pytest.param(_unknown, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="unknown"),
    pytest.param(_completed(Verdict.CONFIRMED, None), REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                 id="confirmed-and-standing"),
    pytest.param(_completed(Verdict.ESCALATED, Undone.LEFT_STANDING), REVERT_FEATURE_FLAG,
                 THE_CONTESTED_FLAG, id="left-standing"),
    pytest.param(_completed(Verdict.ESCALATED, Undone.NOT_ESTABLISHED), REVERT_FEATURE_FLAG,
                 THE_CONTESTED_FLAG, id="not-established"),
    pytest.param(_completed(Verdict.PLATFORM_UNREACHABLE, None, performed=False),
                 REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="not-performed-leaving-something"),
    pytest.param(_completed(Verdict.PLATFORM_UNREACHABLE, None, performed=False,
                            undo_descriptor=None, left_behind_known=False),
                 REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                 id="not-performed-with-nothing-said-of-what-it-left")
]
# Every way it no longer can: put back, left as somebody found it, owing
# nothing, never performed and known to have left nothing, its incident ended
# by a person - or a kind with no way back that is no longer in flight.
EVERY_CHANGE_NO_LONGER_OPEN = [
    pytest.param(_completed(Verdict.REFUTED, Undone.RESTORED), REVERT_FEATURE_FLAG,
                 THE_CONTESTED_FLAG, id="restored"),
    pytest.param(_completed(Verdict.REFUTED, Undone.LEFT_AS_FOUND), REVERT_FEATURE_FLAG,
                 THE_CONTESTED_FLAG, id="left-as-found"),
    pytest.param(_completed(Verdict.CONFIRMED, Undone.NO_UNDO_WAS_OWED), REVERT_FEATURE_FLAG,
                 THE_CONTESTED_FLAG, id="no-undo-owed"),
    pytest.param(_completed(Verdict.PLATFORM_UNREACHABLE, None, performed=False,
                            undo_descriptor=None),
                 REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG, id="not-performed-leaving-nothing"),
    pytest.param(_settled_by_a_person, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                 id="ended-by-a-person"),
    pytest.param(_a_restart_nobody_answered, SCALE_OUT, THE_CONTESTED_APPLICATION,
                 id="a-restart-nobody-answered"),
    pytest.param(_a_restart_never_performed, SCALE_OUT, THE_CONTESTED_APPLICATION,
                 id="a-restart-never-performed")
]


@pytest.mark.integration
@pytest.mark.parametrize(("got_as_far_as", "reaching_with", "for_subject"),
                         EVERY_CHANGE_STILL_OPEN)
def test_a_claim_on_a_subject_another_incident_s_change_may_still_stand_on_names_it(
        got_as_far_as: Callable[[psycopg.Connection, str, str], None],
        reaching_with: ActionType,
        for_subject: str) -> None:
    # Two incidents acting on one flag undo each other: one's put-back takes
    # the other's change away, and one's wait measures the other's change. So a
    # claim on a subject whose change may still stand is refused, naming the
    # incident that holds it, and nothing is written for it.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: got_as_far_as(conn, the_first,
                                              a_hypothesis_recorded_for(the_first)))
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=reaching_with,
                                            subject=for_subject, at=A_LATER_INSTANT)
            ) \
            .then(all_of(
                the_answer_was(SubjectOpen(open_in=the_first)),
                _no_action_was_written_for(conn, the_second)
            ))


@pytest.mark.integration
@pytest.mark.parametrize(("got_as_far_as", "reaching_with", "for_subject"),
                         EVERY_CHANGE_NO_LONGER_OPEN)
def test_a_claim_on_a_subject_whose_change_no_longer_stands_is_claimed(
        got_as_far_as: Callable[[psycopg.Connection, str, str], None],
        reaching_with: ActionType,
        for_subject: str) -> None:
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: got_as_far_as(conn, the_first,
                                              a_hypothesis_recorded_for(the_first)))
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=reaching_with,
                                            subject=for_subject, at=A_LATER_INSTANT)
            ) \
            .then(
                _the_id_of_the_row_claimed_for(conn, the_second, the_second_s_candidate)
            )


@pytest.mark.integration
def test_a_claim_on_a_subject_this_incident_s_own_change_may_still_stand_on_names_it() -> None:
    # Another candidate of the same incident reaching for the same flag: the
    # earlier change is this incident's own, and is named as such.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        the_first_candidate = a_hypothesis_recorded_for(incident_id, rank=1)
        the_second_candidate = a_hypothesis_recorded_for(incident_id, rank=2)

        Scenario() \
            .given(
                calling(lambda: _performed(conn, incident_id, the_first_candidate))
            ) \
            .when(
                lambda: taken_actions.claim(conn, incident_id,
                                            hypothesis_id=the_second_candidate,
                                            action_type=REVERT_FEATURE_FLAG,
                                            subject=THE_CONTESTED_FLAG, at=A_LATER_INSTANT)
            ) \
            .then(
                the_answer_was(SubjectOpen(open_in=incident_id))
            )


@pytest.mark.integration
def test_the_same_name_in_another_realm_is_another_subject() -> None:
    # A flag and an application can be called alike: what one holds open is
    # nothing the other's change touches.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    a_flag_named_like_the_application = THE_CONTESTED_APPLICATION

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: taken_actions.claim(
                    conn, the_first, hypothesis_id=a_hypothesis_recorded_for(the_first),
                    action_type=REVERT_FEATURE_FLAG,
                    subject=a_flag_named_like_the_application, at=SOME_INSTANT))
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=ROLL_BACK_DEPLOYMENT,
                                            subject=THE_CONTESTED_APPLICATION,
                                            at=A_LATER_INSTANT)
            ) \
            .then(
                _the_id_of_the_row_claimed_for(conn, the_second, the_second_s_candidate)
            )


@pytest.mark.integration
def test_a_claim_naming_no_subject_never_stands_in_the_way() -> None:
    # Nothing names what it would hold open, so nothing can be refused for it.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    no_subject = None

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: taken_actions.claim(
                    conn, the_first, hypothesis_id=a_hypothesis_recorded_for(the_first),
                    action_type=REVERT_FEATURE_FLAG, subject=no_subject, at=SOME_INSTANT))
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=REVERT_FEATURE_FLAG,
                                            subject=no_subject, at=A_LATER_INSTANT)
            ) \
            .then(
                _the_id_of_the_row_claimed_for(conn, the_second, the_second_s_candidate)
            )


@pytest.mark.integration
def test_a_restart_holds_its_application_open_while_it_is_in_flight() -> None:
    # A restart leaves nothing to put back, but while it is being made the
    # application is changing under it.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: _a_restart_claimed(conn, the_first,
                                                   a_hypothesis_recorded_for(the_first)))
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=SCALE_OUT,
                                            subject=THE_CONTESTED_APPLICATION,
                                            at=A_LATER_INSTANT)
            ) \
            .then(
                the_answer_was(SubjectOpen(open_in=the_first))
            )


@pytest.mark.integration
def test_a_restart_holds_nothing_open_once_it_has_an_outcome() -> None:
    # Nothing of a restart stands after it: there is nothing to put back, and
    # nothing for another incident's change to undo.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    nothing_to_put_back = None

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_first_s_candidate = a_hypothesis_recorded_for(the_first)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        def a_restart_made_and_judged() -> None:
            _a_restart_claimed(conn, the_first, the_first_s_candidate)
            taken_actions.complete(conn, the_first, hypothesis_id=the_first_s_candidate,
                                   outcome=Verdict.CONFIRMED, undo_descriptor=nothing_to_put_back,
                                   left_behind_known=True)

        Scenario() \
            .given(
                calling(a_restart_made_and_judged)
            ) \
            .when(
                lambda: taken_actions.claim(conn, the_second,
                                            hypothesis_id=the_second_s_candidate,
                                            action_type=SCALE_OUT,
                                            subject=THE_CONTESTED_APPLICATION,
                                            at=A_LATER_INSTANT)
            ) \
            .then(
                _the_id_of_the_row_claimed_for(conn, the_second, the_second_s_candidate)
            )


@pytest.mark.integration
def test_recording_a_change_its_subject_refuses_raises() -> None:
    # A caller writing a finished action whole means it to be there: a claim
    # refused would build a row that isn't, and the caller would never know.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        the_first = an_incident_created_for(conn, dont_care_alert)
        the_second = an_incident_created_for(conn, dont_care_alert)
        the_second_s_candidate = a_hypothesis_recorded_for(the_second)

        Scenario() \
            .given(
                calling(lambda: _performed(conn, the_first, a_hypothesis_recorded_for(the_first)))
            ) \
            .when(attempting(
                lambda: taken_actions.record(conn, the_second,
                                             hypothesis_id=the_second_s_candidate,
                                             action_type=REVERT_FEATURE_FLAG,
                                             subject=THE_CONTESTED_FLAG,
                                             outcome=Verdict.CONFIRMED,
                                             undo_descriptor=THE_WAY_BACK, at=A_LATER_INSTANT,
                                             left_behind_known=True)
            )) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.integration
def test_recording_a_candidate_already_claimed_raises() -> None:
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)

        Scenario() \
            .given(
                calling(lambda: _claimed(conn, incident_id, hypothesis_id))
            ) \
            .when(attempting(
                lambda: taken_actions.record(conn, incident_id, hypothesis_id=hypothesis_id,
                                             action_type=REVERT_FEATURE_FLAG,
                                             subject=THE_CONTESTED_FLAG,
                                             outcome=Verdict.CONFIRMED,
                                             undo_descriptor=THE_WAY_BACK, at=A_LATER_INSTANT,
                                             left_behind_known=True)
            )) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.integration
def test_only_the_rows_of_kinds_with_no_way_back_stop_being_open_at_a_settle() -> None:
    # A settled run will not finish a restart it left in flight, and nothing of
    # a restart stands; a flag change made stands until it is put back. What
    # says so is what another incident's claim on each finds.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        a_flag_s_candidate = a_hypothesis_recorded_for(incident_id, rank=1)
        a_restart_s_candidate = a_hypothesis_recorded_for(incident_id, rank=2)

        def a_flag_and_a_restart_made() -> None:
            _performed(conn, incident_id, a_flag_s_candidate)
            _a_restart_claimed(conn, incident_id, a_restart_s_candidate, at=A_LATER_INSTANT)
            taken_actions.advance(conn, incident_id, hypothesis_id=a_restart_s_candidate,
                                  to=ActionProgress.PERFORMED, undo_descriptor=None)

        Scenario() \
            .given(
                calling(a_flag_and_a_restart_made)
            ) \
            .when(
                lambda: taken_actions.no_longer_open(
                    conn, incident_id, SOME_MOMENT_IT_STOPPED_BEING_OPEN,
                    which=NoLongerOpen.KINDS_WITH_NO_WAY_BACK)
            ) \
            .then(all_of(
                _another_incident_s_claim_on(conn, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                                             is_refused_for=incident_id),
                _another_incident_s_claim_on(conn, SCALE_OUT, THE_CONTESTED_APPLICATION,
                                             is_refused_for=NOBODY)
            ))


@pytest.mark.integration
@pytest.mark.parametrize("withdrawn", [
    pytest.param(True, id="withdrawn"),
    pytest.param(False, id="not-withdrawn")
])
def test_every_row_of_a_withdrawn_incident_and_none_of_another_stops_being_open(
        withdrawn: bool) -> None:
    # A withdrawn incident is neither resolved nor withdrawn again, so what its
    # unwind left standing would hold its subjects open for ever. Asked of the
    # incident's status in the write itself.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        hypothesis_id = a_hypothesis_recorded_for(incident_id)
        # Freed where the incident was withdrawn; held by it where it was not.
        still_held_by = NOBODY if withdrawn else incident_id

        def a_change_left_standing() -> None:
            _completed(Verdict.STOPPED, Undone.LEFT_STANDING)(conn, incident_id, hypothesis_id)
            if withdrawn:
                incidents.withdraw(conn, incident_id, at=SOME_INSTANT)

        Scenario() \
            .given(
                calling(a_change_left_standing)
            ) \
            .when(
                lambda: taken_actions.no_longer_open(
                    conn, incident_id, SOME_MOMENT_IT_STOPPED_BEING_OPEN,
                    which=NoLongerOpen.ROWS_OF_A_WITHDRAWN_INCIDENT)
            ) \
            .then(
                _another_incident_s_claim_on(conn, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                                             is_refused_for=still_held_by)
            )


@pytest.mark.integration
def test_every_row_of_an_incident_stops_being_open_and_no_other_incident_s() -> None:
    # A person ending an incident takes what it left standing into their hands.
    dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        a_hypothesis_recorded_for = partial(_a_hypothesis_recorded_for, conn)
        incident_id = an_incident_created_for(conn, dont_care_alert)
        another_incident_id = an_incident_created_for(conn, dont_care_alert)

        def a_change_made_in_each() -> None:
            _performed(conn, incident_id, a_hypothesis_recorded_for(incident_id))
            _a_restart_claimed(conn, another_incident_id,
                               a_hypothesis_recorded_for(another_incident_id))

        Scenario() \
            .given(
                calling(a_change_made_in_each)
            ) \
            .when(
                lambda: taken_actions.no_longer_open(
                    conn, incident_id, SOME_MOMENT_IT_STOPPED_BEING_OPEN,
                    which=NoLongerOpen.EVERY_ROW)
            ) \
            .then(all_of(
                _another_incident_s_claim_on(conn, REVERT_FEATURE_FLAG, THE_CONTESTED_FLAG,
                                             is_refused_for=NOBODY),
                _another_incident_s_claim_on(conn, SCALE_OUT, THE_CONTESTED_APPLICATION,
                                             is_refused_for=another_incident_id)
            ))


def _a_restart_claimed(conn: psycopg.Connection,
                       incident_id: str,
                       hypothesis_id: str,
                       at: datetime = SOME_INSTANT) -> None:
    taken_actions.claim(conn, incident_id, hypothesis_id=hypothesis_id,
                        action_type=RESTART_SERVICE, subject=THE_CONTESTED_APPLICATION,
                        at=at)


def _no_action_was_written_for(conn: psycopg.Connection,
                               incident_id: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        written = taken_actions.get_by_incident(conn, incident_id)

        if written:
            raise AssertionError(f"Expected no action written for the incident, got {written}")

        return True

    return assertion


def _another_incident_s_claim_on(conn: psycopg.Connection,
                                 action_type: ActionType,
                                 subject: str,
                                 *,
                                 is_refused_for: str | None) -> Assertion[object]:
    """What a claim on `subject`, by an incident of its own made afterwards,
    finds: refused, naming the incident `is_refused_for` - or claimed, where
    that is `NOBODY` and nothing holds the subject open any more."""
    def assertion(_result: object) -> bool:
        dont_care_alert = Alert(service="io-shop", alert_name="HighErrorRate")
        a_later_incident = an_incident_created_for(conn, dont_care_alert)
        answered = taken_actions.claim(
            conn, a_later_incident,
            hypothesis_id=_a_hypothesis_recorded_for(conn, a_later_incident),
            action_type=action_type, subject=subject, at=A_LATER_INSTANT
        )
        found = (isinstance(answered, Claimed) if is_refused_for is NOBODY
                 else answered == SubjectOpen(open_in=is_refused_for))

        if not found:
            wanted = ("claimed" if is_refused_for is NOBODY
                      else f"refused, naming [{is_refused_for}]")
            raise AssertionError(
                f"Expected a later claim on [{subject}] {wanted}, got [{answered}]."
            )

        return True

    return assertion
