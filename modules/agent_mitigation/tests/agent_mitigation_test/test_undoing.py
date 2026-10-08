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
from agent_mitigation.tools import (
    AcceleratorPinRestorer,
    AutoscalingRestorer,
    CapacityRestorer,
    DeploymentRestorer,
    FlagSetter,
)
from argus_core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    AutoscalingRestored,
    CapacityRestored,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagUndo,
    ReplicaUndo,
)
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    a_capacity_restorer_nobody_calls,
    a_restorer_nobody_calls,
    an_accelerator_pin_restorer_nobody_calls,
    an_autoscaling_restorer_nobody_calls,
    an_undo_descriptor_for,
    nobody_can_say,
    nobody_changed_it,
    somebody_changed_it,
)

SOME_FLAG = "monthly-spend-feature"
DONT_CARE_MOMENT = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)


SOME_APPLICATION = "io-shop"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
# The size the deployment was running before Argus made it larger.
THE_COUNT_IT_WAS_RUNNING = 3
# The floor the autoscaler was allowed to fall to before Argus held it still.
THE_FLOOR_IT_WAS_HOLDING = 3
# And the floor it was raised to, which is the ceiling here and is not always: the
# tier asks for whichever is smaller of the ceiling and Argus's own cap.
THE_CEILING_IT_WAS_HELD_AT = 6
# The card Argus held the deployment's pods to.
THE_CARD_IT_WAS_HELD_TO = "Tesla-V100-SXM2-16GB"


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
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=restore,
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=_a_restorer_that_puts_back(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                ),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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
                restore_deployment=_a_restorer_that_cannot(some_failure),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
            .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


@pytest.mark.unit
def test_a_scale_out_is_put_back_by_the_capacity_restorer_and_nothing_else() -> None:
    # The dispatch, for the third kind. A resize sent to something that writes
    # flags would be an undo writing to the wrong system, and one sent to the
    # deployment restorer would put a *revision* back on a deployment whose
    # revision nobody touched.
    set_state = _a_flag_setter()
    restore_deployment = a_restorer_nobody_calls()
    restore_capacity = _a_capacity_restorer_that_puts_back()

    Scenario() \
        .given(
            a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_resize_descriptor_for(SOME_APPLICATION),
                set_state=set_state,
                changed_from_outside=nobody_changed_it(),
                restore_deployment=restore_deployment,
                restore_capacity=restore_capacity,
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_scale_out_put_back_reports_the_application_as_its_subject() -> None:
    Scenario() \
        .given(
            a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_resize_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=_a_capacity_restorer_that_puts_back(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(_it_is_about(SOME_APPLICATION))


@pytest.mark.unit
def test_a_scale_out_put_back_says_the_count_and_the_reconciliation_both_went() -> None:
    # Both halves in the sentence, because both were changed and a reader has
    # only this line. A withdrawal that said "the deployment was put back" would
    # leave the one silently damaging outcome unreadable: a deployment at its
    # declared size that the platform is no longer reconciling looks right from
    # every angle and receives nothing anybody ships to it.
    Scenario() \
        .given(
            a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_resize_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=_a_capacity_restorer_that_puts_back(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_says_what_is_still_changed(f"[{THE_COUNT_IT_WAS_RUNNING}] replicas"),
            _it_says_what_is_still_changed("automated sync was restored")
        ))


@pytest.mark.unit
def test_a_resize_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The quiet half. A deployment back at its declared size while the platform
    # is still not reconciling it looks right from every angle a reader has, and
    # receives nothing anybody ships to it.
    Scenario() \
        .given(
            a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_resize_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=_a_capacity_restorer_that_puts_back(
                    count=True, automated_sync=False
                ),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_a_capacity_restorer_that_raises_leaves_the_resize_not_established() -> None:
    some_failure = "the platform would not answer"
    restore: MagicMock = create_autospec(CapacityRestorer, instance=True)
    restore.side_effect = RuntimeError(some_failure)

    Scenario() \
        .given(
            a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_resize_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=restore,
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
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


def a_resize_descriptor_for(application: str,
                            was_syncing_itself: bool = True) -> ReplicaUndo:
    return ReplicaUndo(
        application=application,
        was_replicas=THE_COUNT_IT_WAS_RUNNING,
        was_syncing_itself=was_syncing_itself
    )


def a_pin_descriptor_for(application: str,
                         was_syncing_itself: bool = True) -> AutoscalerUndo:
    return AutoscalerUndo(
        application=application,
        was_min_replicas=THE_FLOOR_IT_WAS_HOLDING,
        min_replicas_asked_for=THE_CEILING_IT_WAS_HELD_AT,
        was_syncing_itself=was_syncing_itself
    )


def _an_autoscaling_restorer_that_puts_back(
    floor: bool = True,
    automated_sync: bool = True
) -> MagicMock:
    restore: MagicMock = create_autospec(AutoscalingRestorer, instance=True)
    restore.return_value = AutoscalingRestored(
        floor_put_back=floor, automated_sync_put_back=automated_sync
    )

    return restore


def _a_capacity_restorer_that_puts_back(count: bool = True,
                                        automated_sync: bool = True) -> MagicMock:
    restore: MagicMock = create_autospec(CapacityRestorer, instance=True)
    restore.return_value = CapacityRestored(
        count_put_back=count, automated_sync_put_back=automated_sync
    )

    return restore

@pytest.mark.unit
def test_a_pin_is_put_back_by_the_autoscaling_restorer_and_nothing_else() -> None:
    # The dispatch, for the fourth kind. A pin sent to the capacity restorer
    # would put a replica *count* back on a deployment whose count Argus never
    # set: the two act on the same number, and only one of them wrote it.
    set_state = _a_flag_setter()
    restore_capacity = a_capacity_restorer_nobody_calls()

    Scenario() \
        .given(
            a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_pin_descriptor_for(SOME_APPLICATION),
                set_state=set_state,
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=restore_capacity,
                restore_autoscaling=_an_autoscaling_restorer_that_puts_back(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_pin_put_back_reports_the_application_as_its_subject() -> None:
    # An unwind holds several answers at once and has to say which is which. A
    # pin is about an application, as a rollback and a resize are.
    Scenario() \
        .given(
            a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=_an_autoscaling_restorer_that_puts_back(),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(
            _it_is_about(SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_pin_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The half that is easy to lose, and the same half a rollback and a resize
    # can lose. The floor is back, so the controller is free to move again - and
    # the deployment is silently receiving nothing anybody ships to it, because
    # the reconciliation Argus suspended is still suspended.
    Scenario() \
        .given(
            a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=_an_autoscaling_restorer_that_puts_back(
                    floor=True, automated_sync=False
                ),
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_an_autoscaling_restorer_that_raises_leaves_the_pin_not_established() -> None:
    some_failure = "the platform would not answer"
    restore: MagicMock = create_autospec(AutoscalingRestorer, instance=True)
    restore.side_effect = RuntimeError(some_failure)

    Scenario() \
        .given(
            a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=restore,
                restore_accelerator_pin=an_accelerator_pin_restorer_nobody_calls()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


def a_card_pin_descriptor_for(application: str) -> AcceleratorPinUndo:
    return AcceleratorPinUndo(
        application=application,
        was_pinned_to=None,
        pinned_to=THE_CARD_IT_WAS_HELD_TO,
        was_syncing_itself=True
    )


def _an_accelerator_pin_restorer_that_puts_back(
    pin: bool = True,
    automated_sync: bool = True
) -> MagicMock:
    restore: MagicMock = create_autospec(AcceleratorPinRestorer, instance=True)
    restore.return_value = AcceleratorPinRestored(
        pin_put_back=pin, automated_sync_put_back=automated_sync
    )

    return restore


@pytest.mark.unit
def test_a_pin_to_a_card_is_put_back_by_its_own_restorer_and_nothing_else() -> None:
    # The dispatch, for the fifth kind of change. A pin to a card sent to the
    # autoscaling restorer would write a floor onto a deployment whose floor
    # Argus never set: both are pins, and only one of them wrote that field.
    restore_autoscaling = an_autoscaling_restorer_nobody_calls()

    Scenario() \
        .given(
            a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_card_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=restore_autoscaling,
                restore_accelerator_pin=_an_accelerator_pin_restorer_that_puts_back()
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _it_is_about(SOME_APPLICATION),
            _the_autoscaling_restorer_was_not_asked(restore_autoscaling)
        ))


@pytest.mark.unit
def test_a_pin_to_a_card_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The same half every action under a GitOps controller can lose. The pods
    # may land on any card again, and the deployment is silently receiving
    # nothing anybody ships to it.
    Scenario() \
        .given(
            a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_card_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=_an_accelerator_pin_restorer_that_puts_back(
                    pin=True, automated_sync=False
                )
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_an_accelerator_pin_restorer_that_raises_leaves_the_pin_not_established() -> None:
    some_failure = "the platform would not answer"
    restore: MagicMock = create_autospec(AcceleratorPinRestorer, instance=True)
    restore.side_effect = RuntimeError(some_failure)

    Scenario() \
        .given(
            a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: undo_change(
                a_card_pin_descriptor_for(SOME_APPLICATION),
                set_state=_a_flag_setter(),
                changed_from_outside=nobody_changed_it(),
                restore_deployment=a_restorer_nobody_calls(),
                restore_capacity=a_capacity_restorer_nobody_calls(),
                restore_autoscaling=an_autoscaling_restorer_nobody_calls(),
                restore_accelerator_pin=restore
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


def _the_autoscaling_restorer_was_not_asked(restore: MagicMock) -> Assertion[UndoAttempt]:
    def assertion(dont_care_attempt: UndoAttempt) -> bool:
        if restore.called:
            raise AssertionError(
                f"Expected a pin to a card to be put back by its own restorer, and "
                f"the autoscaling restorer was asked {restore.call_args_list}."
            )

        return True

    return assertion
