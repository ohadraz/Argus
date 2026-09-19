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
from argus_core.ids import new_id
from argus_core.models.action import UnreadVerdict, Verdict
from argus_core.models.taken_action import TakenAction
from argus_testkit import Assertion, Scenario

SOME_SPELLING_NO_VERDICT_HAS = "dissolved"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 19, 11, 4, tzinfo=UTC)


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
