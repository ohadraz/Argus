"""One row of the `action` table, as everything that reads it sees it
(spec §11.1, §13).

The column is text and stays text - a row written before a verdict was renamed
is history, and history has to come back out of the table. What this pins is
that the text stops being text here, at the one edge every reader comes through,
rather than at each of them: the dashboard, the postmortem, memory and the
resuming walk all get the row through `class_row(TakenAction)`, so a policy
decided here is decided once.

Three states, and the third is why there are three. A spelling no `Verdict`
knows is not the absence of an outcome: absence means the worker died between
taking the action and recording what it found, which is the one case the
resuming walk cannot answer for itself. Collapsing the unreadable into it would
send a walk to ask the provider about a change whose verdict was already
reached.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from core.ids import new_id
from core.models.action import UnreadVerdict, Verdict
from core.models.planned import Planned
from core.models.taken_action import TakenAction
from core.models.undo_descriptor import (
    ROLL_BACK_DEPLOYMENT_TOOL,
    DeploymentRollbackUndo,
    UndoDescriptor,
)
from core.timestamps import to_iso
from pydantic import ValidationError

SOME_SPELLING_NO_VERDICT_HAS = "dissolved"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 19, 11, 4, tzinfo=UTC)
# The platform's clock, read before the state the plan was worked out from -
# which is before the claim.
SOME_MOMENT_THE_STATE_WAS_READ = datetime(2026, 9, 19, 11, 3, 52, tzinfo=UTC)
SOME_APPLICATION = "io-shop"
SOME_ENTRY_IT_WAS_ON = 2
SOME_PLAN_AS_THE_COLUMN_HOLDS_IT = {
    "kind": "feature-flag",
    "flag": "monthly-spend-feature",
    "was_enabled": True
}


@pytest.mark.unit
def test_an_outcome_a_verdict_spells_reads_back_as_that_verdict() -> None:
    Scenario() \
        .given(
            a_row := _a_row_whose_outcome_is(Verdict.REFUTED.value)
        ) \
        .when(
            lambda: TakenAction(**a_row)
        ) \
        .then(
            _the_outcome_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_an_outcome_no_verdict_spells_reads_back_unread_rather_than_raising() -> None:
    # A row this version cannot read is a row an older one wrote, and the
    # incident holding it is one a human is already looking at. Refusing to
    # load it would take the dashboard, the postmortem and the undo down with
    # the verdict nobody can spell - so it is carried, with its spelling, and
    # the two places that decide anything on it decide what that means.
    Scenario() \
        .given(
            a_row := _a_row_whose_outcome_is(SOME_SPELLING_NO_VERDICT_HAS)
        ) \
        .when(
            lambda: TakenAction(**a_row)
        ) \
        .then(
            _the_outcome_is(UnreadVerdict(SOME_SPELLING_NO_VERDICT_HAS))
        )


@pytest.mark.unit
def test_a_row_claimed_and_never_completed_has_no_outcome_at_all() -> None:
    # The state the third one exists to stay out of. This is the worker that
    # stopped between acting and recording, and the only row whose change may
    # be out there unmeasured - which is a question for the provider, and the
    # walk asks it on this and on nothing else.
    Scenario() \
        .given(
            a_row := _a_row_whose_outcome_is(None)
        ) \
        .when(
            lambda: TakenAction(**a_row)
        ) \
        .then(
            _the_outcome_is(None)
        )


@pytest.mark.unit
def test_a_row_claimed_with_a_plan_reads_back_the_change_it_planned() -> None:
    # The column is JSON, and a resumed walk compares the estate with the
    # plan's fields - so the plan stops being JSON here, as the kind its tag
    # says, for the reason the outcome stops being text here. And the two
    # columns become the one value they are: a plan and the moment its state
    # was read, neither of which means anything without the other.
    some_plan = DeploymentRollbackUndo(
        application=SOME_APPLICATION,
        was_on_history_id=SOME_ENTRY_IT_WAS_ON,
        was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
        rolled_back_to_revision="544cef36a8eaf45c5b030c3d5c21473d8176cef3",
        rolled_back_to_history_id=SOME_ENTRY_IT_WAS_ON - 1,
        was_syncing_itself=True
    )
    a_row = {
        **_a_row_whose_outcome_is(None),
        "plan": {
            "kind": "deployment-revision",
            "tool": ROLL_BACK_DEPLOYMENT_TOOL,
            "application": some_plan.application,
            "was_on_history_id": some_plan.was_on_history_id,
            "was_on_revision": some_plan.was_on_revision,
            "rolled_back_to_revision": some_plan.rolled_back_to_revision,
            "rolled_back_to_history_id": some_plan.rolled_back_to_history_id,
            "was_syncing_itself": some_plan.was_syncing_itself,
            "written_at": None
        },
        "since": to_iso(SOME_MOMENT_THE_STATE_WAS_READ)
    }

    Scenario() \
        .given(
            a_row
        ) \
        .when(
            lambda: TakenAction(**a_row)
        ) \
        .then(
            _it_planned(Planned(descriptor=some_plan, since=SOME_MOMENT_THE_STATE_WAS_READ))
        )


@pytest.mark.unit
def test_a_row_claimed_with_no_plan_reads_back_with_none() -> None:
    # A restart and a discard plan nothing: there is nothing to compare the
    # estate with, and no moment the state was read at.
    a_row = {**_a_row_whose_outcome_is(None), "plan": None, "since": None}

    Scenario() \
        .given(
            a_row
        ) \
        .when(
            lambda: TakenAction(**a_row)
        ) \
        .then(
            _it_planned(None)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("plan", "since"), [
    pytest.param(SOME_PLAN_AS_THE_COLUMN_HOLDS_IT, None, id="a-plan-nobody-dated"),
    pytest.param(None, to_iso(SOME_MOMENT_THE_STATE_WAS_READ), id="a-moment-dating-nothing")
])
def test_a_row_with_half_a_plan_is_refused(plan: dict[str, Any] | None,
                                           since: str | None) -> None:
    # The schema stores both or neither, so a row with one is not a row this
    # table wrote. Read as no plan, a resumed walk would act again on a claim
    # whose change it was told nothing about; read as a plan, it would ask
    # whether anything landed after a moment nobody recorded.
    a_row = {**_a_row_whose_outcome_is(None), "plan": plan, "since": since}

    Scenario() \
        .given(
            a_row
        ) \
        .when(attempting(
            lambda: TakenAction(**a_row)
        )) \
        .then(
            an_error_was_raised(ValidationError)
        )


def _a_row_whose_outcome_is(outcome: str | None) -> dict[str, Any]:
    """One claimed action as the cursor hands it over, outcome aside."""
    return {
        "id": new_id(),
        "incident_id": new_id(),
        "hypothesis_id": new_id(),
        "type": "revert_feature_flag",
        "subject": "monthly-spend-feature",
        "has_a_way_back": True,
        "undo_descriptor": None,
        "outcome": outcome,
        "taken_at": THE_MOMENT_IT_WAS_CLAIMED
    }


def _the_outcome_is(expected: Verdict | UnreadVerdict | None) -> Assertion[TakenAction]:
    def assertion(action: TakenAction) -> bool:
        # Two rows can spell an outcome the same way and mean different things
        # by it, so the type is half the assertion: `UnreadVerdict("refuted")`
        # equals `Verdict.REFUTED` and is not one.
        if action.outcome != expected or type(action.outcome) is not type(expected):
            raise AssertionError(
                f"Expected the outcome to read back as [{expected!r}], got "
                f"[{action.outcome!r}]."
            )

        return True

    return assertion


def _it_planned(expected: Planned[UndoDescriptor] | None) -> Assertion[TakenAction]:
    def assertion(action: TakenAction) -> bool:
        if action.planned != expected:
            raise AssertionError(
                f"Expected the plan to read back as [{expected!r}], got "
                f"[{action.planned!r}]."
            )

        return True

    return assertion
