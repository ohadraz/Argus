from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import UndoAttempt, Undone, undo_change
from agent_mitigation.tools import FlagSetter
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    an_undo_descriptor_for,
    nobody_can_say,
    nobody_changed_it,
    somebody_changed_it,
)

"""Putting one change back, where it is still Argus's to put back.

The condition is a question about the provider's record, not about the flag's
current value: has anybody but Argus changed this flag since Argus wrote it. A
value comparison answers a different question - what does the provider's
evaluation cache currently serve - and answers it wrongly for as long as that
cache is stale, which is exactly the window in which a human's deliberate change
would be overwritten.
"""

SOME_FLAG = "monthly-spend-feature"
DONT_CARE_MOMENT = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)


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
                changed_from_outside=nobody_changed_it()
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
                changed_from_outside=somebody_changed_it()
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
    a_descriptor_from_before = {
        "tool": "set_feature_flag",
        "flag": SOME_FLAG,
        "environment": "production",
        "was_enabled": True,
    }

    Scenario() \
        .given(
            a_descriptor_from_before
        ) \
        .when(
            lambda: undo_change(
                a_descriptor_from_before,
                set_state=set_state,
                changed_from_outside=nobody_changed_it()
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
                changed_from_outside=nobody_can_say()
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
                changed_from_outside=asked.record
            )
        ) \
        .then(
            _it_was_asked_from(asked, the_moment_argus_wrote)
        )
    

def _a_flag_setter() -> MagicMock:
    setter: MagicMock = create_autospec(FlagSetter)
    setter.return_value = {}

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
