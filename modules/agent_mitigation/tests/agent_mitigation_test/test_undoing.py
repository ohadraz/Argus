"""Putting one change back, where it is still Argus's to put back.

The condition is a question about the provider's record, not about the flag's
current value: has anybody but Argus changed this flag since Argus wrote it. A
value comparison answers a different question - what does the provider's
evaluation cache currently serve - and answers it wrongly for as long as that
cache is stale, which is exactly the window in which a human's deliberate change
would be overwritten.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import (
    UndoAttempt,
    Undone,
    undo_change,
)
from agent_mitigation.tools import DeploymentRestorer, FlagSetter
from argus_core.models import (
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagUndo,
)
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    a_restorer_nobody_calls,
    an_undo_descriptor_for,
    nobody_can_say,
    nobody_changed_it,
    somebody_changed_it,
)

SOME_FLAG = "monthly-spend-feature"
DONT_CARE_MOMENT = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)


SOME_APPLICATION = "io-shop"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"


@pytest.mark.unit
def test_a_flag_nobody_touched_is_put_back() -> None:
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: undo_change(
                an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                set_state=set_state,
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _the_flag_was_set_to(set_state, SOME_FLAG, enabled=True)
        ))


@pytest.mark.unit
def test_a_flag_somebody_changed_is_left_as_found() -> None:
    # The case a value comparison gets wrong. The flag may well still read as
    # what Argus wrote - the provider's evaluation is a cache, and a change made
    # a moment ago has not reached it - but the record says somebody has been in
    # there, and their change is not Argus's to overwrite.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: undo_change(
                an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                set_state=set_state,
                changed_from_outside=somebody_changed_it(),
                restore_deployment=a_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.LEFT_AS_FOUND),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_when_argus_wrote_is_not_acted_on() -> None:
    # Rows written before the descriptor carried the moment. Guessing from the
    # current value is the failure this whole check exists to remove, so an
    # answer nobody can date is one of the three answers rather than a restore.
    set_state = _a_flag_setter()
    a_descriptor_from_before = FlagUndo(
        flag=SOME_FLAG,
        was_enabled=True,
        environment="production"
    )

    Scenario() \
        .given(
            a_descriptor_from_before
        ) \
        .when(
            lambda: undo_change(
                a_descriptor_from_before,
                set_state=set_state,
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_record_that_cannot_be_read_is_not_written_over() -> None:
    # "Nobody can say" and "nobody changed it" are opposite facts, and the whole
    # value of this check is the difference between them.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: undo_change(
                an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                set_state=set_state,
                changed_from_outside=nobody_can_say(),
                restore_deployment=a_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_the_record_is_asked_about_from_the_moment_argus_wrote() -> None:
    # Not from the moment of the undo, and not from a lookback window: a change
    # made before Argus wrote is not somebody overriding Argus, and asking from
    # anywhere but the write would count it as one.
    the_moment_argus_wrote = ACTION_TIME
    asked = _a_record_asked_about(answering=False)

    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(
                SOME_FLAG, was_enabled=True,written_at=the_moment_argus_wrote)
        ) \
        .when(
            lambda: undo_change(
                descriptor,
                set_state=_a_flag_setter(),
                changed_from_outside=asked.record,
                restore_deployment=a_restorer_nobody_calls()
            )
        ) \
        .then(
            _it_was_asked_from(asked, the_moment_argus_wrote)
        )
    

def _a_flag_setter() -> MagicMock:
    setter: MagicMock = create_autospec(FlagSetter)
    setter.return_value = an_undo_descriptor_for(SOME_FLAG)

    return setter


class _ARecordAskedAbout:
    """The question the undo asked, kept so a test can assert on it."""

    def __init__(self, answering: bool) -> None:
        self.asked_about: tuple[str, datetime] | None = None
        self._answer = answering

    def record(self, flag: str, since: datetime) -> bool | None:
        self.asked_about = (flag, since)

        return self._answer


def _a_record_asked_about(answering: bool) -> _ARecordAskedAbout:
    return _ARecordAskedAbout(answering)


def _it_reports(expected: Undone) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.outcome is not expected:
            raise AssertionError(
                f"Expected the undo to report [{expected}], got "
                f"[{attempt.outcome}]: {attempt.detail}."
            )

        return True

    return assertion


def _the_flag_was_set_to(set_state: MagicMock,
                         flag: str,
                         enabled: bool) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        set_state.assert_called_once_with(flag, enabled)

        return True

    return assertion


def _nothing_was_written(set_state: MagicMock) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        if set_state.called:
            raise AssertionError(
                f"Expected nothing to be written, and the flag was set: "
                f"{set_state.call_args}."
            )

        return True

    return assertion


def _it_was_asked_from(asked: _ARecordAskedAbout,
                       moment: datetime) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        if asked.asked_about != (SOME_FLAG, moment):
            raise AssertionError(
                f"Expected the record to be asked about [{SOME_FLAG}] from "
                f"[{moment}], and it was asked {asked.asked_about}."
            )

        return True

    return assertion


def a_rollback_descriptor_for(application: str,
                              was_syncing_itself: bool = True) -> DeploymentRollbackUndo:
    return DeploymentRollbackUndo(
        application=application,
        was_on_history_id=2,
        was_on_revision=THE_REVISION_IT_WAS_ON,
        was_syncing_itself=was_syncing_itself
    )


def _a_restorer_that_puts_back(revision: bool = True,
                               automated_sync: bool = True) -> MagicMock:
    restore: MagicMock = create_autospec(DeploymentRestorer, instance=True)
    restore.return_value = DeploymentRestored(
        revision_put_back=revision, automated_sync_put_back=automated_sync
    )

    return restore


def _a_restorer_that_cannot(why: str) -> MagicMock:
    restore: MagicMock = create_autospec(DeploymentRestorer, instance=True)
    restore.side_effect = RuntimeError(why)

    return restore


@pytest.mark.unit
def test_a_rollback_is_put_back_by_the_restorer_rather_than_the_flag_setter() -> None:
    # The dispatch. Two kinds of change reach this, and the one that is not a
    # flag must not be sent to something that writes flags - which, before the
    # descriptor was a union, is exactly what would have happened.
    set_state = _a_flag_setter()
    restore = _a_restorer_that_puts_back()

    Scenario() \
        .given(
            a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
            .when(
            lambda: undo_change(
                a_rollback_descriptor_for(SOME_APPLICATION),
                set_state=set_state,
                changed_from_outside=nobody_changed_it(),
                restore_deployment=restore
            )
        ) \
            .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_rollback_put_back_reports_the_application_as_its_subject() -> None:
    # An unwind holds several answers at once and has to say which is which.
    # A rollback is about an application, where a flag revert is about a flag.
    Scenario() \
        .given(
            a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
            .when(
            lambda: undo_change(
                a_rollback_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=_a_restorer_that_puts_back()
            )
        ) \
            .then(
            _it_is_about(SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_rollback_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The half that is easy to lose. The revision is back, so the deployment
    # looks right - and it is silently receiving nothing anybody ships to it,
    # because the reconciliation Argus suspended is still suspended. Reported
    # as not established, which is what escalates it to somebody.
    Scenario() \
        .given(
            a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
            .when(
            lambda: undo_change(
                a_rollback_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=_a_restorer_that_puts_back(
                    revision=True, automated_sync=False
                )
            )
        ) \
            .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_a_restorer_that_raises_leaves_the_rollback_not_established() -> None:
    # Nothing raises out of an undo. An unwind runs over every change an
    # incident made, and one deployment nobody can reach must not stop the
    # others being put back.
    some_failure = "the platform refused"

    Scenario() \
        .given(
            a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
            .when(
            lambda: undo_change(
                a_rollback_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=_a_restorer_that_cannot(some_failure)
            )
        ) \
            .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


def _it_is_about(subject: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.subject != subject:
            raise AssertionError(
                f"Expected the answer to be about [{subject}], and it was about "
                f"[{attempt.subject}]."
            )

        return True

    return assertion


def _it_says_what_is_still_changed(mentioned: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if mentioned not in attempt.detail:
            raise AssertionError(
                f"Expected the report to name [{mentioned}], and it said: "
                f"{attempt.detail}"
            )

        return True

    return assertion
