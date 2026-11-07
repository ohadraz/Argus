"""When an action was taken, as every reader of an incident says it.

The row is a claim written before the agent taking the action is called in, so
it is the one moment that must not date the action wherever the account says
when it was taken.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from argus_core import new_id
from argus_core.events import ActionTaken, IncidentEvent, VerdictReached
from argus_core.models import ActionProgress, FlagUndo, TakenAction, Verdict
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
def test_an_action_never_performed_is_dated_by_the_verdict_that_says_so() -> None:
    # An attempt that ended before its write is announced by nothing, and its
    # verdict is the one line that says it. Dated by its claim, a roll-back the
    # platform refused stood before the agent reaching for it was called in.
    its_verdict_at = SOME_CLAIM + timedelta(milliseconds=860)

    Scenario() \
        .given(
            its_verdict := [_not_performed(SOME_CANDIDATE, its_verdict_at)]
        ) \
        .when(
            lambda: when_it_was_taken(_claimed_and_not_performed(SOME_CANDIDATE), its_verdict)
        ) \
        .then(
            the_answer_was(its_verdict_at)
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    lambda: [],
    lambda: [_announced(SOME_OTHER_CANDIDATE, SOME_CLAIM + timedelta(seconds=1))],
    lambda: [_not_performed(SOME_OTHER_CANDIDATE, SOME_CLAIM + timedelta(seconds=1))],
    lambda: [_performed(SOME_CANDIDATE, SOME_CLAIM + timedelta(minutes=3))]
], ids=["nothing-said", "another-candidate-announced", "another-candidate-not-performed",
        "only-its-performed-verdict"])
def test_an_action_no_line_dates_is_dated_by_its_row(
        said: Callable[[], list[IncidentEvent]]) -> None:
    # An older walk never announced its actions, another candidate's line is
    # another action's, and a performed action's verdict comes minutes after
    # its change was made.
    Scenario() \
        .given(
            account := said()
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


def _claimed_and_not_performed(hypothesis_id: str) -> TakenAction:
    """A roll-back's row as a walk leaves it when the platform refused it before
    its write: claimed at `SOME_CLAIM`, and nothing left behind."""
    return TakenAction(id=new_id(),
                       incident_id=SOME_INCIDENT,
                       hypothesis_id=hypothesis_id,
                       type="roll-back-deployment",
                       subject="dont-care",
                       has_a_way_back=True,
                       undo_descriptor=None,
                       outcome=Verdict.PLATFORM_UNREACHABLE,
                       taken_at=SOME_CLAIM,
                       progress=ActionProgress.NOT_PERFORMED,
                       left_behind_known=True)


def _announced(hypothesis_id: str, at: datetime) -> ActionTaken:
    return ActionTaken(incident_id=SOME_INCIDENT,
                       hypothesis_id=hypothesis_id,
                       action_type="revert-feature-flag",
                       subject="dont-care",
                       at=at)


def _not_performed(hypothesis_id: str, at: datetime) -> VerdictReached:
    return VerdictReached(incident_id=SOME_INCIDENT,
                          hypothesis_id=hypothesis_id,
                          outcome=Verdict.PLATFORM_UNREACHABLE,
                          action_type="roll-back-deployment",
                          subject="dont-care",
                          performed=False,
                          judged=False,
                          at=at)


def _performed(hypothesis_id: str, at: datetime) -> VerdictReached:
    return VerdictReached(incident_id=SOME_INCIDENT,
                          hypothesis_id=hypothesis_id,
                          outcome=Verdict.CONFIRMED,
                          action_type="revert-feature-flag",
                          subject="dont-care",
                          at=at)
