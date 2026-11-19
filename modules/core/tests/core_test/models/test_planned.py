"""A change worked out before it is made, what a flag reads as now, and what a
walk resumed after its worker died finds of a change.

A plan is written by the write tier, carried across the MCP wire to the walk,
stored on the claim as JSONB, and handed back across the wire to the write that
compares the estate with it. Four crossings, every one of them JSON, and the
descriptor inside is a tagged union - so what this pins is that a plan of each
kind comes off the wire as the change it was, and goes back on it unchanged.

`since` is what a resumed walk asks the platform's record about: whether
anything landed after it. A moment spelled differently on the way back out is
compared against the platform's own timestamps and quietly loses the
comparison, which is why the wire shape is spelled out here rather than built
from the model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from core.models.planned import FlagState, Made, NotMade, Planned
from core.models.undo_descriptor import (
    PIN_AUTOSCALER_TOOL,
    PIN_TO_ACCELERATOR_TOOL,
    ROLL_BACK_DEPLOYMENT_TOOL,
    SCALE_OUT_TOOL,
    SET_FEATURE_FLAG_TOOL,
    AcceleratorPinUndo,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    FlagUndo,
    ReplicaUndo,
    UndoDescriptor,
)
from core.timestamps import to_iso
from pydantic import ValidationError

SOME_APPLICATION = "io-shop"
SOME_FLAG = "monthly-spend-feature"
SOME_CARD = "Tesla-V100-SXM2-16GB"
SOME_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
SOME_REVISION_TO_ROLL_BACK_TO = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
SOME_ENTRY_IT_WAS_ON = 2
SOME_ENTRY_TO_ROLL_BACK_TO = SOME_ENTRY_IT_WAS_ON - 1
SOME_COUNT_IT_WAS_RUNNING = 3
SOME_COUNT_TO_ASK_FOR = SOME_COUNT_IT_WAS_RUNNING * 2
SOME_FLOOR_IT_HAD = 2
SOME_FLOOR_TO_ASK_FOR = SOME_FLOOR_IT_HAD * 3
# The platform's own clock, read before the state the plan was worked out from.
THE_MOMENT_THE_STATE_WAS_READ = datetime(2026, 11, 18, 9, 30, 12, tzinfo=UTC)
# When the estate says a claim's change was made, and a moment a reader of the
# answer might try to put in its place.
SOME_MOMENT_IT_WAS_MADE = THE_MOMENT_THE_STATE_WAS_READ + timedelta(minutes=2)
SOME_OTHER_MOMENT = SOME_MOMENT_IT_WAS_MADE + timedelta(minutes=5)


def _the_wire_shape_of_a_planned_flag_change() -> dict[str, Any]:
    """A flag change worked out and not yet made: no environment written to,
    no moment to date a write by."""
    return {
        "kind": "feature-flag",
        "tool": SET_FEATURE_FLAG_TOOL,
        "flag": SOME_FLAG,
        "was_enabled": True,
        "environment": None,
        "written_at": None
    }


def _the_wire_shape_of_a_planned_rollback() -> dict[str, Any]:
    """A rollback worked out and not yet made, the entry it returns to chosen."""
    return {
        "kind": "deployment-revision",
        "tool": ROLL_BACK_DEPLOYMENT_TOOL,
        "application": SOME_APPLICATION,
        "was_on_history_id": SOME_ENTRY_IT_WAS_ON,
        "was_on_revision": SOME_REVISION_IT_WAS_ON,
        "rolled_back_to_revision": SOME_REVISION_TO_ROLL_BACK_TO,
        "rolled_back_to_history_id": SOME_ENTRY_TO_ROLL_BACK_TO,
        "was_syncing_itself": True,
        "written_at": None
    }


def _the_wire_shape_of_a_planned_scale_out() -> dict[str, Any]:
    """A scale-out worked out and not yet made."""
    return {
        "kind": "replica-count",
        "tool": SCALE_OUT_TOOL,
        "application": SOME_APPLICATION,
        "was_replicas": SOME_COUNT_IT_WAS_RUNNING,
        "replicas_asked_for": SOME_COUNT_TO_ASK_FOR,
        "was_syncing_itself": True,
        "written_at": None
    }


def _the_wire_shape_of_a_planned_autoscaler_pin() -> dict[str, Any]:
    """An autoscaler's floor raise worked out and not yet made."""
    return {
        "kind": "autoscaler-floor",
        "tool": PIN_AUTOSCALER_TOOL,
        "application": SOME_APPLICATION,
        "was_min_replicas": SOME_FLOOR_IT_HAD,
        "min_replicas_asked_for": SOME_FLOOR_TO_ASK_FOR,
        "was_syncing_itself": True,
        "written_at": None
    }


def _the_wire_shape_of_a_planned_accelerator_pin() -> dict[str, Any]:
    """A pin to a card worked out and not yet made."""
    return {
        "kind": "accelerator-pin",
        "tool": PIN_TO_ACCELERATOR_TOOL,
        "application": SOME_APPLICATION,
        "was_pinned_to": None,
        "pinned_to": SOME_CARD,
        "was_syncing_itself": True,
        "written_at": None
    }


EVERY_KIND_OF_PLAN = [
    (_the_wire_shape_of_a_planned_flag_change(), FlagUndo),
    (_the_wire_shape_of_a_planned_rollback(), DeploymentRollbackUndo),
    (_the_wire_shape_of_a_planned_scale_out(), ReplicaUndo),
    (_the_wire_shape_of_a_planned_autoscaler_pin(), AutoscalerUndo),
    (_the_wire_shape_of_a_planned_accelerator_pin(), AcceleratorPinUndo)
]
EVERY_KIND_OF_PLAN_IDS = ["flag", "rollback", "scale-out", "autoscaler-pin", "accelerator-pin"]


@pytest.mark.unit
@pytest.mark.parametrize(("descriptor", "member"), EVERY_KIND_OF_PLAN,
                         ids=EVERY_KIND_OF_PLAN_IDS)
def test_a_plan_comes_off_the_wire_as_the_change_it_plans_and_goes_back_unchanged(
        descriptor: dict[str, Any], member: type) -> None:
    # Off the wire as the kind its tag says, because the write it is handed
    # back to compares the estate with that kind's fields; back on it as it
    # came, because the claim stores what the walk was handed and the write
    # reads what the claim stored.
    a_plan = {"descriptor": descriptor, "since": to_iso(THE_MOMENT_THE_STATE_WAS_READ)}

    Scenario() \
        .given(
            a_plan
        ) \
        .when(
            lambda: Planned[UndoDescriptor].model_validate(a_plan)
        ) \
        .then(all_of(
            _it_plans_a(member),
            _it_was_worked_out_from_state_read_at(THE_MOMENT_THE_STATE_WAS_READ),
            _it_serializes_back_to(a_plan)
        ))


@pytest.mark.unit
def test_a_plan_that_does_not_say_when_its_state_was_read_is_rejected() -> None:
    # No default. A plan with no moment cannot tell the platform's record of a
    # change made since it from one made before it, and a guess - now, say -
    # would take somebody's change for the state Argus planned from.
    a_plan_with_no_moment = {"descriptor": _the_wire_shape_of_a_planned_rollback()}

    Scenario() \
        .given(
            a_plan_with_no_moment
        ) \
        .when(
            attempting(lambda: Planned[UndoDescriptor].model_validate(a_plan_with_no_moment))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("since")
        ))


@pytest.mark.unit
def test_a_flag_state_that_does_not_say_when_the_provider_read_it_is_rejected() -> None:
    # The moment is what a flag's plan is dated by. Without it, the provider's
    # change history since the plan has no "since" to be read from.
    a_state_with_no_moment = {"enabled": True}

    Scenario() \
        .given(
            a_state_with_no_moment
        ) \
        .when(
            attempting(lambda: FlagState.model_validate(a_state_with_no_moment))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("read_at")
        ))


@pytest.mark.unit
def test_a_change_found_made_cannot_be_changed_once_found() -> None:
    # The answer a resumed walk acts on, and dates its row by: one moved after
    # it was found would date the change by something the estate never said.
    a_change_found_made = Made[FlagUndo](
        descriptor=FlagUndo.model_validate(_the_wire_shape_of_a_planned_flag_change()),
        made_at=SOME_MOMENT_IT_WAS_MADE
    )

    Scenario() \
        .given(
            a_change_found_made
        ) \
        .when(
            attempting(lambda: _redated(a_change_found_made, SOME_OTHER_MOMENT))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_still_says_it_was_made_at(a_change_found_made, SOME_MOMENT_IT_WAS_MADE)
        ))


@pytest.mark.unit
def test_a_change_found_made_is_never_read_off_the_wire_as_one_found_not_made() -> None:
    # Both answers cross the same wire. A made answer read as not made, its
    # fields dropped, would send the walk to write a change already made.
    a_made_answer_on_the_wire = {
        "descriptor": _the_wire_shape_of_a_planned_flag_change(),
        "made_at": to_iso(SOME_MOMENT_IT_WAS_MADE)
    }

    Scenario() \
        .given(
            a_made_answer_on_the_wire
        ) \
        .when(
            attempting(lambda: NotMade[FlagUndo].model_validate(a_made_answer_on_the_wire))
        ) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            _it_complains_about("made_at")
        ))


def _redated(made: Made[FlagUndo], moment: datetime) -> None:
    made.made_at = moment


def _it_still_says_it_was_made_at(made: Made[FlagUndo],
                                  moment: datetime) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        if made.made_at != moment:
            raise AssertionError(
                f"Expected the change found made still dated [{moment}], got [{made.made_at}]."
            )

        return True

    return assertion


def _it_plans_a(member: type) -> Assertion[Planned[UndoDescriptor]]:
    def assertion(planned: Planned[UndoDescriptor]) -> bool:
        if not isinstance(planned.descriptor, member):
            raise AssertionError(
                f"Expected the plan to carry a [{member.__name__}], got a "
                f"[{type(planned.descriptor).__name__}]."
            )

        return True

    return assertion


def _it_was_worked_out_from_state_read_at(moment: datetime
                                          ) -> Assertion[Planned[UndoDescriptor]]:
    def assertion(planned: Planned[UndoDescriptor]) -> bool:
        if planned.since != moment:
            raise AssertionError(
                f"Expected the plan dated by state read at [{moment}], got "
                f"[{planned.since}]."
            )

        return True

    return assertion


def _it_serializes_back_to(expected: dict[str, Any]) -> Assertion[Planned[UndoDescriptor]]:
    def assertion(planned: Planned[UndoDescriptor]) -> bool:
        serialized = planned.model_dump(mode="json")

        if serialized != expected:
            raise AssertionError(
                f"Expected the plan to serialize back to {expected}, got {serialized}"
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
