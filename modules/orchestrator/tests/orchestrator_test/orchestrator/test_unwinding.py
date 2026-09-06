from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import UndoAttempt, Undone
from argus_core.ids import new_id
from argus_testkit import Assertion, Scenario, all_of
from orchestrator import unwinding
from orchestrator.repository.actions import Action
from orchestrator.unwinding import unwind_incident

"""Putting back everything an incident changed, once nobody wants it walked.

The other half of a withdrawal. Marking the incident stops the walk; this is
what makes stopping honest - a walk halted mid-flight has production in a state
it chose for a reason that no longer applies, and nobody but Argus knows what
that state replaced.

Every recorded change goes through the same conditional undo, and none of them
is filtered by what the walk made of it. A change already put back reads as one
somebody else changed, so it is left alone - which makes running this twice cost
nothing, and makes it safe over an incident whose walk had already tidied up
after itself.
"""

_DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.fixture
def undo() -> MagicMock:
    return cast(MagicMock, create_autospec(unwinding.UndoChange, instance=True))


@pytest.fixture
def record_note() -> MagicMock:
    return cast(MagicMock, create_autospec(unwinding.RecordNote, instance=True))


@pytest.mark.unit
def test_every_change_the_incident_recorded_is_put_back(
    undo: MagicMock, record_note: MagicMock
) -> None:
    a_first_change = _an_undo_descriptor_for("monthly-spend-feature")
    a_second_change = _an_undo_descriptor_for("checkout-kill-switch")
    undo.return_value = _restored("dont care")

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                a_first_change, a_second_change)
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                actions_of=_reading(an_incident_that_changed),
                undo=undo,
                record_note=record_note,
            )
        ) \
        .then(
            _the_changes_put_back(undo, a_first_change, a_second_change)
        )


@pytest.mark.unit
def test_an_action_that_changed_nothing_has_nothing_to_put_back(
    undo: MagicMock, record_note: MagicMock
) -> None:
    # An action the gate refused, or one that could not be performed at all.
    # There is no descriptor because there was no change, and calling the undo
    # for it would ask the provider about a flag nobody set.
    Scenario() \
        .given(
            an_incident_that_changed_nothing := _an_incident_whose_action_carries_no_descriptor()
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                actions_of=_reading(an_incident_that_changed_nothing),
                undo=undo,
                record_note=record_note,
            )
        ) \
        .then(
            _nothing_was_undone(undo)
        )


@pytest.mark.unit
def test_what_each_undo_found_is_recorded_on_the_incident(
    undo: MagicMock, record_note: MagicMock
) -> None:
    # A human reading a withdrawn incident has to be able to tell what state
    # Argus left behind without going and looking at the environment.
    some_detail = "flag [monthly-spend-feature] was left as found"
    undo.return_value = UndoAttempt(
        flag="monthly-spend-feature",
        outcome=Undone.LEFT_AS_FOUND,
        detail=some_detail,
    )

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                _an_undo_descriptor_for("monthly-spend-feature"))
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                actions_of=_reading(an_incident_that_changed),
                undo=undo,
                record_note=record_note,
            )
        ) \
        .then(all_of(
            _one_note_was_written(record_note),
            _the_note_says(record_note, result=some_detail),
            _the_note_names(record_note, Undone.LEFT_AS_FOUND)
        ))


@pytest.mark.unit
def test_one_change_that_cannot_be_read_does_not_stop_the_others(
    undo: MagicMock, record_note: MagicMock
) -> None:
    # The unwind is the last thing that happens to an incident. A flag the
    # provider could not answer for is a flag left behind either way, and
    # letting it take the rest with it leaves more behind, not less.
    undo.side_effect = [
        UndoAttempt(
            flag="monthly-spend-feature",
            outcome=Undone.NOT_ESTABLISHED,
            detail="dont care",
        ),
        _restored("checkout-kill-switch"),
    ]

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                _an_undo_descriptor_for("monthly-spend-feature"),
                _an_undo_descriptor_for("checkout-kill-switch"))
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                actions_of=_reading(an_incident_that_changed),
                undo=undo,
                record_note=record_note,
            )
        ) \
        .then(all_of(
            _both_changes_were_attempted(undo),
            _both_were_recorded(record_note)
        ))


def _the_changes_put_back(undo: MagicMock,
                          *expected: dict[str, Any]) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        attempted = [call.args[0] for call in undo.call_args_list]

        if attempted != list(expected):
            raise AssertionError(
                f"Expected the changes {expected} to be put back, got {attempted}."
            )

        return True

    return assertion


def _nothing_was_undone(undo: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if undo.call_count:
            raise AssertionError(
                f"Expected nothing to be put back, got "
                f"{[call.args[0] for call in undo.call_args_list]}."
            )

        return True

    return assertion


def _one_note_was_written(record_note: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if record_note.call_count != 1:
            raise AssertionError(
                f"Expected one note, got [{record_note.call_count}]."
            )

        return True

    return assertion


def _the_note_says(record_note: MagicMock, result: str) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        written = record_note.call_args.kwargs["result"]

        if written != result:
            raise AssertionError(
                f"Expected the note to read [{result!r}], got [{written!r}]."
            )

        return True

    return assertion


def _the_note_names(record_note: MagicMock, outcome: Undone) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        action = record_note.call_args.kwargs["action"]

        if str(outcome) not in action:
            raise AssertionError(
                f"Expected the note to name [{outcome}], got [{action!r}]."
            )

        return True

    return assertion


def _both_changes_were_attempted(undo: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if undo.call_count != 2:
            raise AssertionError(
                f"Expected both changes to be attempted, got [{undo.call_count}]."
            )

        return True

    return assertion


def _both_were_recorded(record_note: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if record_note.call_count != 2:
            raise AssertionError(
                f"Expected both attempts to be recorded, got "
                f"[{record_note.call_count}]."
            )

        return True

    return assertion


def _restored(flag: str) -> UndoAttempt:
    return UndoAttempt(
        flag=flag, outcome=Undone.RESTORED, detail=f"flag [{flag}] was put back"
    )


def _an_undo_descriptor_for(flag: str, was_enabled: bool = True) -> dict[str, Any]:
    return {
        "tool": "set_feature_flag",
        "flag": flag,
        "environment": "production",
        "was_enabled": was_enabled,
    }


def _an_incident_that_changed(*descriptors: dict[str, Any]) -> list[Action]:
    return [_an_action_carrying(descriptor) for descriptor in descriptors]


def _an_incident_whose_action_carries_no_descriptor() -> list[Action]:
    return [_an_action_carrying(None)]


def _reading(recorded: list[Action]) -> Callable[[str], list[Action]]:
    """The incident's own changes, as the unwind asks for them."""
    def actions_of(_incident_id: str) -> list[Action]:
        return recorded

    return actions_of


def _an_action_carrying(undo_descriptor: dict[str, Any] | None) -> Action:
    return Action(
        id=new_id(),
        incident_id=_DONT_CARE_INCIDENT_ID,
        hypothesis_id=new_id(),
        type="revert-feature-flag",
        target="dont-care-flag",
        reversible=True,
        tier="write",
        undo_descriptor=undo_descriptor,
        outcome="dont care",
        taken_at=datetime.now(UTC),
        approved_by=None,
    )
