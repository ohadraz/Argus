"""When an action was taken, as every reader of an incident says it.

The row is a claim written before the agent taking the action is called in, so
it is the one moment that must not date the action wherever the account says
when it was taken.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core import new_id
from argus_core.events import ActionTaken
from argus_core.models import FlagUndo, TakenAction, Verdict
from argus_incidents import when_it_was_taken
from argus_testkit import Scenario, the_answer_was

SOME_CLAIM = datetime(2026, 10, 26, 18, 4, 48, 597000, tzinfo=UTC)
SOME_INCIDENT = new_id()
SOME_CANDIDATE = new_id()
SOME_OTHER_CANDIDATE = new_id()


@pytest.mark.unit
def test_an_announced_action_is_dated_by_its_announcement() -> None:
    # Dated by its claim, a roll-back stood a second before the agent that
    # took it was called in.
    announced_at = SOME_CLAIM + timedelta(milliseconds=438)

    Scenario() \
        .given(
            its_announcement := [_announced(SOME_CANDIDATE, announced_at)]
        ) \
        .when(
            lambda: when_it_was_taken(_claimed(SOME_CANDIDATE), its_announcement)
        ) \
        .then(
            the_answer_was(announced_at)
        )


@pytest.mark.unit
def test_an_action_announced_twice_is_dated_by_the_last_announcement() -> None:
    # A walk resumed after announcing an action and before taking it announces
    # it again, and the second is the one it was taken by.
    the_resumed_announcement = SOME_CLAIM + timedelta(minutes=3)

    Scenario() \
        .given(
            two_announcements := [_announced(SOME_CANDIDATE, SOME_CLAIM + timedelta(seconds=1)),
                                  _announced(SOME_CANDIDATE, the_resumed_announcement)]
        ) \
        .when(
            lambda: when_it_was_taken(_claimed(SOME_CANDIDATE), two_announcements)
        ) \
        .then(
            the_answer_was(the_resumed_announcement)
        )


@pytest.mark.unit
@pytest.mark.parametrize("candidates_announced", [
    [],
    [SOME_OTHER_CANDIDATE]
], ids=["nothing-announced", "another-candidate-announced"])
def test_an_action_the_account_says_nothing_of_is_dated_by_its_row(
        candidates_announced: list[str]) -> None:
    # An older walk never announced its actions, and another candidate's
    # announcement is another action's.
    Scenario() \
        .given(
            account := [_announced(candidate, SOME_CLAIM + timedelta(seconds=1))
                        for candidate in candidates_announced]
        ) \
        .when(
            lambda: when_it_was_taken(_claimed(SOME_CANDIDATE), account)
        ) \
        .then(
            the_answer_was(SOME_CLAIM)
        )


def _claimed(hypothesis_id: str) -> TakenAction:
    return TakenAction(id=new_id(),
                       incident_id=SOME_INCIDENT,
                       hypothesis_id=hypothesis_id,
                       type="revert-feature-flag",
                       subject="dont-care",
                       has_a_way_back=True,
                       undo_descriptor=FlagUndo(flag="dont-care", was_enabled=True),
                       outcome=Verdict.CONFIRMED,
                       taken_at=SOME_CLAIM)


def _announced(hypothesis_id: str, at: datetime) -> ActionTaken:
    return ActionTaken(incident_id=SOME_INCIDENT,
                       hypothesis_id=hypothesis_id,
                       action_type="revert-feature-flag",
                       subject="dont-care",
                       at=at)
