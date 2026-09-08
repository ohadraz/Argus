from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_core.models.undo_descriptor import SET_FEATURE_FLAG_TOOL, UndoDescriptor
from argus_core.timestamps import to_iso
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from pydantic import ValidationError

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
"""

SOME_FLAG = "monthly-spend-feature"
SOME_ENVIRONMENT = "production"
THE_MOMENT_ARGUS_WROTE = datetime(2026, 9, 6, 17, 38, tzinfo=UTC)


@pytest.mark.unit
def test_a_descriptor_says_which_flag_to_restore_and_to_what() -> None:
    Scenario() \
        .given(
            a_write := _the_wire_shape_of_a_write(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: UndoDescriptor.model_validate(a_write)
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
            attempting(lambda: UndoDescriptor.model_validate(a_write_naming_no_flag))
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
            attempting(lambda: UndoDescriptor.model_validate(a_write_naming_no_state))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("was_enabled")
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_when_argus_wrote_is_still_a_descriptor() -> None:
    # Two real cases, and neither is malformed: an action chosen but not yet
    # taken has nothing to date, and the provider sometimes returns no time for
    # a write it accepted. The undo has an answer for both - it says the state
    # could not be established - and it can only give it if the record admits
    # the moment is missing rather than refusing to exist.
    a_change_nobody_dated = {
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": SOME_FLAG,
        "was_enabled": True
    }

    Scenario() \
        .given(
            a_change_nobody_dated
        ) \
        .when(
            lambda: UndoDescriptor.model_validate(a_change_nobody_dated)
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
            lambda: UndoDescriptor.model_validate(a_write).model_dump(mode="json")
        ) \
        .then(
            _it_is_the_wire_shape(a_write)
        )


def _the_wire_shape_of_a_write(flag: str, was_enabled: bool) -> dict[str, Any]:
    """One write as the write tier reports it, before anything has read it."""
    return {
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": flag,
        "environment": SOME_ENVIRONMENT,
        "was_enabled": was_enabled,
        "written_at": to_iso(THE_MOMENT_ARGUS_WROTE)
    }


def _it_restores(flag: str, to_state: bool) -> Assertion[UndoDescriptor]:
    def assertion(descriptor: UndoDescriptor) -> bool:
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
