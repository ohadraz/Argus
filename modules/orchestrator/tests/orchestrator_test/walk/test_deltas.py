"""What a node may change, and how its change reaches the walk's state.

A node reports what it found and did; the incident's status is derived from
that, by `status_after`, once - so a node that could name a status would be a
second place deciding it, and the two could disagree.

The delta is flat where the state is grouped. Two things follow, and both are
held here: every field a node may set is one field of the state, by name and
type, so the two cannot drift apart; and a change to one field of a group
reaches LangGraph as the whole group, since LangGraph replaces each key it is
handed and a group sent in part would lose the rest of itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    an_error_was_raised,
    attempting,
    the_answer_was,
)
from core.models import Alert, FlagUndo, IncidentStatus, RestartService, RevertFeatureFlag
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.state import (
    ActionInFlight,
    CandidateCursor,
    IncidentState,
    RoundEvidence,
    WhatWasLearnt,
)
from pydantic import BaseModel, ValidationError

from orchestrator_test.framework.builders import a_determined_hypothesis, an_incident_state

# A status a node might once have named, which none may any more.
SOME_STATUS = IncidentStatus.ESCALATED
DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"
SOME_FLAG = "monthly-spend-feature"
SOME_MOMENT = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)
SOME_REASON = "the error rate stayed above its threshold"
# The groups of the state, by the field each is held in - what this file pins
# the delta against.
THE_GROUPS: dict[str, type[BaseModel]] = {
    "cursor": CandidateCursor,
    "evidence": RoundEvidence,
    "history": WhatWasLearnt,
    "action": ActionInFlight
}
# What the state holds that no node sets: what the walk is about, and the
# count of its steps, which the wrapper every node runs in keeps.
NOT_A_NODES_TO_SET = {"incident_id", "alert", "status", "steps"}
# What a node says rather than sets.
SAID_NOT_SET = "narration"


@pytest.mark.unit
def test_a_node_cannot_name_the_incident_s_status() -> None:
    # Refused rather than ignored, as every field the delta does not carry is:
    # a status dropped in silence would leave the node believing it had moved
    # the incident.
    Scenario() \
        .when(attempting(lambda: StateDelta.model_validate({"status": SOME_STATUS}))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
def test_every_field_a_node_may_set_is_one_field_of_the_state() -> None:
    # By name and by type, the delta's own being the state's or the state's
    # with `None` beside it - a node that sets nothing leaves the field unset.
    Scenario() \
        .when(lambda: _what_the_delta_names()) \
        .then(_each_names_one_field_of_the_state_as_typed())


@pytest.mark.unit
def test_every_field_of_the_state_a_node_may_set_is_one_the_delta_carries() -> None:
    # The other direction: a field added to the state that no delta can carry
    # is a field no node could ever change.
    Scenario() \
        .when(lambda: _what_the_state_holds_for_nodes_to_set()) \
        .then(_each_is_carried_by_the_delta())


@pytest.mark.unit
def test_a_change_to_one_field_of_a_group_arrives_with_the_group_whole() -> None:
    Scenario() \
        .given(
            some_candidate := a_determined_hypothesis(DONT_CARE_INCIDENT_ID),
            some_other_candidate := a_determined_hypothesis(DONT_CARE_INCIDENT_ID),
            a_walk_on_its_first_candidate := _a_state_with(
                cursor=CandidateCursor(hypothesis=some_candidate,
                                       candidates=[some_candidate, some_other_candidate],
                                       candidate_index=0)
            )
        ) \
        .when(lambda: StateDelta(candidate_index=1).as_updates(a_walk_on_its_first_candidate)) \
        .then(the_answer_was({
            "cursor": CandidateCursor(hypothesis=some_candidate,
                                      candidates=[some_candidate, some_other_candidate],
                                      candidate_index=1)
        }))


@pytest.mark.unit
def test_a_proposal_starts_an_action_of_its_own() -> None:
    # What was found when acting on the last one is not this one's.
    Scenario() \
        .given(
            a_walk_that_acted := _a_state_with(action=ActionInFlight(
                proposed_action=_a_revert(), acted_at=SOME_MOMENT, action_because=SOME_REASON
            )),
            the_next_action := RestartService(service=DONT_CARE_ALERT.service)
        ) \
        .when(lambda: StateDelta(proposed_action=the_next_action).as_updates(a_walk_that_acted)) \
        .then(the_answer_was({"action": ActionInFlight(proposed_action=the_next_action)}))


@pytest.mark.unit
def test_no_proposal_leaves_no_action_in_flight() -> None:
    Scenario() \
        .given(
            a_walk_that_acted := _a_state_with(action=ActionInFlight(
                proposed_action=_a_revert(), acted_at=SOME_MOMENT
            ))
        ) \
        .when(lambda: StateDelta(proposed_action=None).as_updates(a_walk_that_acted)) \
        .then(the_answer_was({"action": None}))


@pytest.mark.unit
def test_what_acting_found_is_written_onto_the_action_in_flight() -> None:
    Scenario() \
        .given(
            a_walk_about_to_act := _a_state_with(
                action=ActionInFlight(proposed_action=(the_action := _a_revert()))
            )
        ) \
        .when(
            lambda: StateDelta(acted_at=SOME_MOMENT, action_because=SOME_REASON)
            .as_updates(a_walk_about_to_act)
        ) \
        .then(the_answer_was({"action": ActionInFlight(
            proposed_action=the_action, acted_at=SOME_MOMENT, action_because=SOME_REASON
        )}))


@pytest.mark.unit
def test_nothing_found_when_acting_is_written_over_what_was() -> None:
    # Told outright, a `None` is what the node found, and it stands in place of
    # an earlier finding rather than letting that one through.
    Scenario() \
        .given(
            a_walk_that_acted := _a_state_with(action=ActionInFlight(
                proposed_action=(the_action := _a_revert()),
                acted_at=SOME_MOMENT,
                action_because=SOME_REASON
            ))
        ) \
        .when(
            lambda: StateDelta(acted_at=None, action_because=None)
            .as_updates(a_walk_that_acted)
        ) \
        .then(the_answer_was({"action": ActionInFlight(proposed_action=the_action)}))


@pytest.mark.unit
@pytest.mark.parametrize("field", sorted(
    field for group in THE_GROUPS.values() for field in group.model_fields
))
def test_each_field_of_a_group_is_folded_into_its_group(field: str) -> None:
    # Into its own group and nothing else: LangGraph keeps only the keys it has
    # a channel for, so a field folded anywhere else would be dropped unseen.
    Scenario() \
        .given(
            a_walk_with_an_action := _a_state_with(
                action=ActionInFlight(proposed_action=_a_revert())
            ),
            the_change := StateDelta.model_validate(
                {field: _what_the_state_holds(a_walk_with_an_action, field)}
            )
        ) \
        .when(lambda: the_change.as_updates(a_walk_with_an_action)) \
        .then(_it_arrived_only_as(_the_group_holding(field)))


@pytest.mark.unit
def test_what_acting_found_with_no_action_in_flight_is_dropped() -> None:
    # Its one reader reads it only beside a proposed action, so with none there
    # is nothing for it to be about.
    Scenario() \
        .given(a_walk_with_no_action := _a_state_with(action=None)) \
        .when(lambda: StateDelta(action_because=SOME_REASON).as_updates(a_walk_with_no_action)) \
        .then(the_answer_was({"action": None}))


def _a_state_with(**groups: Any) -> IncidentState:
    return an_incident_state(DONT_CARE_ALERT, IncidentStatus.MITIGATING) \
        .model_copy(update=groups)


def _a_revert() -> RevertFeatureFlag:
    return RevertFeatureFlag(flag=SOME_FLAG,
                             enabled=False,
                             undo_descriptor=FlagUndo(flag=SOME_FLAG, was_enabled=True))


def _the_group_holding(field: str) -> str:
    return next(name for name, group in THE_GROUPS.items() if field in group.model_fields)


def _what_the_state_holds(state: IncidentState, field: str) -> Any:
    return getattr(getattr(state, _the_group_holding(field)), field)


def _it_arrived_only_as(group: str) -> Assertion[dict[str, Any]]:
    def assertion(updates: dict[str, Any]) -> bool:
        if list(updates) != [group]:
            raise AssertionError(
                f"Expected the change to arrive as [{group}] alone, it arrived as "
                f"{sorted(updates)}."
            )

        return True

    return assertion


def _what_the_delta_names() -> dict[str, Any]:
    return {name: field.annotation for name, field in StateDelta.model_fields.items()
            if name != SAID_NOT_SET}


def _what_the_state_holds_for_nodes_to_set() -> dict[str, Any]:
    """Every field a node may set, by name and type: the state's own fields
    but the groups, and every field of every group."""
    held = {name: field.annotation for name, field in IncidentState.model_fields.items()
            if name not in NOT_A_NODES_TO_SET and name not in THE_GROUPS}
    grouped = [(name, field.annotation) for group in THE_GROUPS.values()
               for name, field in group.model_fields.items()]
    names = [name for name, _ in grouped]
    repeated = {name for name in names if names.count(name) > 1 or name in held}

    if repeated:
        raise AssertionError(
            f"Expected every field a node may set to be held in one place, "
            f"{sorted(repeated)} are held in more than one."
        )

    return held | dict(grouped)


def _each_names_one_field_of_the_state_as_typed() -> Assertion[dict[str, Any]]:
    def assertion(named: dict[str, Any]) -> bool:
        held = _what_the_state_holds_for_nodes_to_set()
        unheld = sorted(name for name in named if name not in held)
        mistyped = {name: (typed, held[name]) for name, typed in named.items()
                    if name in held and typed not in (held[name], held[name] | None)}

        if unheld or mistyped:
            raise AssertionError(
                f"Expected every field the delta carries to be one the state holds, "
                f"typed as the state types it or with None beside it. Not held: "
                f"{unheld}. Typed otherwise (delta, state): {mistyped}."
            )

        return True

    return assertion


def _each_is_carried_by_the_delta() -> Assertion[dict[str, Any]]:
    def assertion(held: dict[str, Any]) -> bool:
        carried = _what_the_delta_names()
        uncarried = sorted(name for name in held if name not in carried)

        if uncarried:
            raise AssertionError(
                f"Expected every field of the state a node may set to be carried by "
                f"the delta, {uncarried} are not."
            )

        return True

    return assertion
