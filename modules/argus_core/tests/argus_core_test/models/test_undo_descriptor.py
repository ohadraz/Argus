"""The record of one change, in the shape that puts it back (spec §7.3, §13).

What the write tier returns and what an undo reads back, hours later and two
processes away. Everything here is load-bearing far from where it was written:
the flag and the state say what to restore, and `written_at` is the moment the
provider's own record gets asked about - a restore that cannot date Argus's
write cannot tell a human's deliberate change from its own.

Read out of raw JSON by hand, a descriptor missing one of those surfaces as a
`KeyError` inside the undo, at the one moment nothing can be done about it. It
crosses an MCP boundary and a JSONB column on the way, so the shape holds only
if something checks it.

`kind` is what says which sort of change this is, and it is on the wire because
a descriptor is read back by a process that holds nothing but the JSON. It is
spelled out here rather than imported from the model: this file is what pins the
wire shape, and a test that took the tag from the code it checks would agree
with any change to it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_core.models.undo_descriptor import (
    ROLL_BACK_CONFIGURATION_TOOL,
    SET_FEATURE_FLAG_TOOL,
    ConfigRollbackUndo,
    FlagUndo,
    UndoDescriptor,
    parse_undo_descriptor,
)
from argus_core.timestamps import to_iso
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from pydantic import ValidationError

SOME_FLAG = "monthly-spend-feature"
SOME_ENVIRONMENT = "production"
THE_MOMENT_ARGUS_WROTE = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)
A_FLAG_CHANGE = "feature-flag"
A_CONFIG_ROLLBACK = "config-revision"
SOME_APPLICATION = "io-shop"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"


@pytest.mark.unit
def test_a_descriptor_says_which_flag_to_restore_and_to_what() -> None:
    Scenario() \
        .given(
            a_write := _the_wire_shape_of_a_write(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: parse_undo_descriptor(a_write)
        ) \
        .then(all_of(
            _it_restores(SOME_FLAG, to_state=True),
            _it_dates_the_write_to(THE_MOMENT_ARGUS_WROTE),
            _the_tool_that_undoes_it_is(SET_FEATURE_FLAG_TOOL)
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_which_flag_is_rejected() -> None:
    # Rejected where it is built, not where it is used. The undo is the last
    # thing an incident does, and a descriptor that cannot name its flag turns
    # the tidying-up into the failure.
    a_write_naming_no_flag = {
        "kind": A_FLAG_CHANGE,
        "tool": SET_FEATURE_FLAG_TOOL,
        "environment": SOME_ENVIRONMENT,
        "was_enabled": True,
        "written_at": to_iso(THE_MOMENT_ARGUS_WROTE)
    }

    Scenario() \
        .given(
            a_write_naming_no_flag
        ) \
        .when(
            attempting(lambda: parse_undo_descriptor(a_write_naming_no_flag))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("flag")
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_which_state_to_restore_is_rejected() -> None:
    # There is no safe default here. Guessing "off" would clear a flag that was
    # on before Argus touched it, which is a change nobody asked for wearing the
    # word "restore".
    a_write_naming_no_state = {
        "kind": A_FLAG_CHANGE,
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": SOME_FLAG,
        "environment": SOME_ENVIRONMENT,
        "written_at": to_iso(THE_MOMENT_ARGUS_WROTE)
    }

    Scenario() \
        .given(
            a_write_naming_no_state
        ) \
        .when(
            attempting(lambda: parse_undo_descriptor(a_write_naming_no_state))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("was_enabled")
        ))


@pytest.mark.unit
def test_a_descriptor_that_says_nothing_about_its_kind_is_rejected() -> None:
    # The union decides which sort of change a stored descriptor describes, and
    # it decides by the tag. An untagged one is refused rather than assumed to
    # be the only kind there is today: the assumption would be right exactly
    # until it was not, and it would be wrong inside an undo.
    a_change_that_says_nothing_about_its_kind = {
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": SOME_FLAG,
        "was_enabled": True
    }

    Scenario() \
        .given(
            a_change_that_says_nothing_about_its_kind
        ) \
        .when(
            attempting(
                lambda: parse_undo_descriptor(a_change_that_says_nothing_about_its_kind)
            )
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("kind")
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_when_argus_wrote_is_still_a_descriptor() -> None:
    # Two real cases, and neither is malformed: an action chosen but not yet
    # taken has nothing to date, and the provider sometimes returns no time for
    # a write it accepted. The undo has an answer for both - it says the state
    # could not be established - and it can only give it if the record admits
    # the moment is missing rather than refusing to exist.
    a_change_nobody_dated = {
        "kind": A_FLAG_CHANGE,
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": SOME_FLAG,
        "was_enabled": True
    }

    Scenario() \
        .given(
            a_change_nobody_dated
        ) \
        .when(
            lambda: parse_undo_descriptor(a_change_nobody_dated)
        ) \
        .then(all_of(
            _it_restores(SOME_FLAG, to_state=True),
            _it_dates_the_write_to(None)
        ))


@pytest.mark.unit
def test_a_descriptor_goes_back_to_the_wire_as_it_came_off_it() -> None:
    # It is stored as JSON and read back by a later process, so the shape it
    # serializes to is the shape it has to accept. A moment that came in as the
    # provider spelled it and went out spelled differently would be compared
    # against the provider's own timestamps and quietly lose the comparison.
    a_write = _the_wire_shape_of_a_write(SOME_FLAG, was_enabled=False)

    Scenario() \
        .given(
            a_write
        ) \
        .when(
            lambda: parse_undo_descriptor(a_write).model_dump(mode="json")
        ) \
        .then(
            _it_is_the_wire_shape(a_write)
        )


@pytest.mark.unit
def test_a_rollback_descriptor_records_both_things_it_changed() -> None:
    # The difference between this descriptor and the flag's. Rolling a
    # deployment back means suspending the platform's own reconciliation
    # first - it refuses otherwise - so the action changed two things, and an
    # undo restoring only the revision would leave the deployment silently
    # receiving nothing anybody ships to it.
    Scenario() \
        .given(
            a_rollback := _the_wire_shape_of_a_rollback(was_syncing_itself=True)
        ) \
        .when(
            lambda: parse_undo_descriptor(a_rollback)
        ) \
        .then(all_of(
            _it_returns_to(THE_REVISION_IT_WAS_ON, history_id=2),
            _it_restores_automated_sync_to(True),
            _the_tool_that_undoes_it_is(ROLL_BACK_CONFIGURATION_TOOL)
        ))


@pytest.mark.unit
def test_a_rollback_descriptor_keeps_sync_off_where_it_was_found_off() -> None:
    # An application somebody had already stopped reconciling must be left
    # stopped. Restoring it to "on" because that is the usual arrangement
    # would be Argus turning on a thing it did not turn off.
    Scenario() \
        .given(
            a_rollback := _the_wire_shape_of_a_rollback(was_syncing_itself=False)
        ) \
        .when(
            lambda: parse_undo_descriptor(a_rollback)
        ) \
        .then(
            _it_restores_automated_sync_to(False)
        )


@pytest.mark.unit
def test_a_rollback_descriptor_that_does_not_say_what_sync_was_is_rejected() -> None:
    # No default, for the reason `was_enabled` has none: both states are
    # equally real, and a guess would be recorded as a restore.
    incomplete = _the_wire_shape_of_a_rollback(was_syncing_itself=True)
    del incomplete["was_syncing_itself"]

    Scenario() \
        .given(
            incomplete
        ) \
        .when(
            attempting(lambda: parse_undo_descriptor(incomplete))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("was_syncing_itself")
        ))


@pytest.mark.unit
def test_the_kind_is_what_chooses_between_the_two_sorts_of_change() -> None:
    # The tag decides which member a stored object is. A reader that picked a
    # member for itself would be right today and silently wrong the first time
    # a third kind is stored.
    Scenario() \
        .given(
            a_rollback := _the_wire_shape_of_a_rollback(was_syncing_itself=True)
        ) \
        .when(
            lambda: parse_undo_descriptor(a_rollback)
        ) \
        .then(
            _it_is_a(ConfigRollbackUndo)
        )


@pytest.mark.unit
def test_a_rollback_descriptor_goes_back_to_the_wire_as_it_came_off_it() -> None:
    a_rollback = _the_wire_shape_of_a_rollback(was_syncing_itself=True)

    Scenario() \
        .given(
            a_rollback
        ) \
        .when(
            lambda: parse_undo_descriptor(a_rollback).model_dump(mode="json")
        ) \
        .then(
            _it_is_the_wire_shape(a_rollback)
        )


def _the_wire_shape_of_a_rollback(was_syncing_itself: bool) -> dict[str, Any]:
    """One rollback as the write tier reports it, before anything has read it."""
    return {
        "kind": A_CONFIG_ROLLBACK,
        "tool": ROLL_BACK_CONFIGURATION_TOOL,
        "application": SOME_APPLICATION,
        "was_on_history_id": 2,
        "was_on_revision": THE_REVISION_IT_WAS_ON,
        "was_syncing_itself": was_syncing_itself,
        "written_at": to_iso(THE_MOMENT_ARGUS_WROTE)
    }


def _the_wire_shape_of_a_write(flag: str, was_enabled: bool) -> dict[str, Any]:
    """One write as the write tier reports it, before anything has read it."""
    return {
        "kind": A_FLAG_CHANGE,
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": flag,
        "environment": SOME_ENVIRONMENT,
        "was_enabled": was_enabled,
        "written_at": to_iso(THE_MOMENT_ARGUS_WROTE)
    }


def _it_restores(flag: str, to_state: bool) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if not isinstance(descriptor, FlagUndo):
            raise AssertionError(
                f"Expected a descriptor restoring a flag, got a [{descriptor.kind}] "
                f"one."
            )

        if (descriptor.flag, descriptor.was_enabled) != (flag, to_state):
            raise AssertionError(
                f"Expected a descriptor restoring [{flag}] to [{to_state}], got "
                f"[{descriptor.flag}] to [{descriptor.was_enabled}]."
            )

        return True

    return assertion


def _it_dates_the_write_to(moment: datetime | None) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if descriptor.written_at != moment:
            raise AssertionError(
                f"Expected the write to be dated [{moment}], and it was dated "
                f"[{descriptor.written_at}]."
            )

        return True

    return assertion


def _the_tool_that_undoes_it_is(tool: str) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if descriptor.tool != tool:
            raise AssertionError(
                f"Expected [{tool}] to be the tool that undoes it, got "
                f"[{descriptor.tool}]."
            )

        return True

    return assertion


def _it_is_the_wire_shape(expected: dict[str, Any]) -> Assertion[dict[str, Any]]:
    def assertion(serialized: dict[str, Any]) -> bool:
        if serialized != expected:
            raise AssertionError(
                f"Expected the descriptor to serialize back to {expected}, got "
                f"{serialized}."
            )

        return True

    return assertion


def _it_complains_about(field: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if field not in str(error):
            raise AssertionError(
                f"Expected the rejection to name [{field}], and it said: {error}."
            )

        return True

    return assertion


def _it_returns_to(revision: str, history_id: int) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if not isinstance(descriptor, ConfigRollbackUndo):
            raise AssertionError(
                f"Expected a descriptor returning a deployment, got a "
                f"[{descriptor.kind}] one."
            )

        if (descriptor.was_on_revision, descriptor.was_on_history_id) != (
            revision, history_id
        ):
            raise AssertionError(
                f"Expected a descriptor returning to [{revision}] at entry "
                f"[{history_id}], got [{descriptor.was_on_revision}] at "
                f"[{descriptor.was_on_history_id}]."
            )

        return True

    return assertion


def _it_restores_automated_sync_to(syncing: bool) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if not isinstance(descriptor, ConfigRollbackUndo):
            raise AssertionError(
                f"Expected a descriptor returning a deployment, got a "
                f"[{descriptor.kind}] one."
            )

        if descriptor.was_syncing_itself != syncing:
            raise AssertionError(
                f"Expected the deployment's automated sync to be restored to "
                f"[{syncing}], and it was [{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_is_a(kind: type) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
        if not isinstance(descriptor, kind):
            raise AssertionError(
                f"Expected the tag to select a {kind.__name__}, and it selected "
                f"a {type(descriptor).__name__}."
            )

        return True

    return assertion
