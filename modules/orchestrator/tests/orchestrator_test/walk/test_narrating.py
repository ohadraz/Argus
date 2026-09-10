from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_core.events import StatusChanged
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.withdrawal import IsStillWanted
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk import ports
from orchestrator.walk.narrating import Narration, with_status

"""The one place a status is persisted, and the one place it is published.

Nodes do their work and say what they did; this decides where the incident
stands and writes it down. Keeping that in a wrapper rather than in each node is
what makes "a status is written only when the incident enters it" a property of
the graph instead of a rule five nodes have to remember - and the rule was
already being forgotten.

It is also where the walk finds out it is no longer wanted. Every node the graph
runs passes through here first, so one question asked in one place stops all of
them - and asked before the node rather than after, because a node that has
already toggled a flag cannot be stopped by anything this wrapper does with its
return value.
"""

type Node = Callable[[IncidentState], dict[str, Any]]
type NodeResult = dict[str, Any]

SOME_MAX_ROUNDS = 3
DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"
DONT_CARE_NARRATION = Narration(action="dont care")
DONT_CARE_ACTOR = Actor.ORCHESTRATOR


@pytest.fixture
def transition_incident() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.TransitionIncident, instance=True))


@pytest.fixture
def record_note() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordNote, instance=True))


@pytest.mark.unit
def test_a_node_that_moved_the_incident_transitions_it_once(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    Scenario() \
        .given(
            an_investigation_that_found_something := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            an_investigation_that_found_something,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_being_investigated)
        ) \
        .then(all_of(
            _the_incident_was_moved_once_to(IncidentStatus.MITIGATING,
                                            transition_incident),
            _the_move_was_narrated_as(IncidentStatus.MITIGATING,
                                      transition_incident),
            _nothing_was_noted(record_note)))


@pytest.mark.unit
def test_a_node_that_moved_nothing_writes_no_transition(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # The guarantee the whole change exists for. A status set here and
    # overwritten one node later is a claim about the incident that the timeline
    # cannot take back, so it is never written in the first place.
    Scenario() \
        .given(
            a_gate_refusing_an_action := _a_node_returning(
                {"proposed_action": None},
                narration=Narration(action="action rejected at the tier gate")
            ),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_gate_refusing_an_action,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_the_incident_was_not_moved(transition_incident))


@pytest.mark.unit
def test_a_node_that_moved_nothing_still_says_what_it_did(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Work that settles nothing is still work a human reading the incident needs
    # to see. Silence here is how a rejected action became indistinguishable
    # from an action that was never proposed.
    some_refusal = "action rejected at the tier gate"
    some_reason = "the proposed action carries no undo descriptor"

    Scenario() \
        .given(
            a_gate_refusing_an_action := _a_node_returning(
                {"proposed_action": None},
                narration=Narration(action=some_refusal, result=some_reason)
            ),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_gate_refusing_an_action,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_exactly_one_note_said(some_refusal, some_reason, record_note))


@pytest.mark.unit
def test_the_actor_on_a_row_is_the_agent_the_node_was_registered_as(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Which agent a node belongs to is fixed when the graph is built. It was
    # being repeated inside every call as a constant, which is one more thing a
    # node could get wrong about itself.
    Scenario() \
        .given(
            a_node_finding_a_candidate := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            a_node_finding_a_candidate,
            Actor.INVESTIGATOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_being_investigated)
        ) \
        .then(_the_move_was_attributed_to(Actor.INVESTIGATOR, transition_incident))


@pytest.mark.unit
def test_the_narration_never_reaches_the_graphs_state(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # What a node said is written to the timeline and dropped. Left in the
    # updates it would become a field of `IncidentState`, checkpointed forever,
    # describing whichever node happened to run last.
    Scenario() \
        .given(
            a_narrating_node := _a_node_returning(
                {"proposed_action": None}, narration=Narration(action="dont care")
            ),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_narrating_node,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_the_updates_are({"proposed_action": None}))


@pytest.mark.unit
def test_the_derived_status_is_returned_with_the_nodes_work(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Routing reads the status off the state, as it always has. What changed is
    # who put it there.
    Scenario() \
        .given(
            an_investigation_that_found_something := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            an_investigation_that_found_something,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_is_still_wanted())(an_incident_being_investigated)
        ) \
        .then(all_of(
            _the_updates_carry("status", IncidentStatus.MITIGATING),
            _the_updates_carry("candidate_index", 0))
        )


@pytest.mark.unit
def test_a_withdrawn_incident_stops_the_node_before_it_runs(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Before, not after. A node that has already toggled a flag cannot be
    # stopped by anything done with its return value, so the question is asked
    # while there is still an answer worth having.
    ran: list[str] = []

    Scenario() \
        .given(
            a_node_that_would_have_acted := _a_node_that_records_being_run(ran),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_node_that_would_have_acted,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_the_incident_was_withdrawn())(an_incident_mitigating)
        ) \
        .then(all_of(
            _the_node_never_ran(ran),
            _the_updates_are({"status": IncidentStatus.WITHDRAWN}),
            _the_incident_was_not_moved(transition_incident),
            _nothing_was_noted(record_note))
        )


@pytest.mark.unit
def test_an_incident_nobody_has_is_not_walked_either(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # An incident whose row is gone cannot want anything. Reading that as "still
    # wanted" is how a walk goes on writing rows for an incident that no longer
    # exists - which is exactly the state a suite leaves behind when it empties
    # the database between cases.
    ran: list[str] = []

    Scenario() \
        .given(
            a_node_that_would_have_acted := _a_node_that_records_being_run(ran),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_node_that_would_have_acted,
            DONT_CARE_ACTOR,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            record_note=record_note,
            still_wanted=_there_is_no_such_incident())(an_incident_mitigating)
        ) \
        .then(all_of(
            _the_node_never_ran(ran),
            _the_incident_was_not_moved(transition_incident))
        )


def _the_incident_is_still_wanted() -> IsStillWanted:
    """Nobody has withdrawn it - which is every case but the two that say so.

    Injected rather than left to default, because the real one reads the
    incident back out of the database and a unit test has none.
    """
    def still_wanted(dont_care_incident_id: str) -> bool:
        return True

    return still_wanted


def _the_incident_was_withdrawn() -> IsStillWanted:
    def still_wanted(dont_care_incident_id: str) -> bool:
        return False

    return still_wanted


def _there_is_no_such_incident() -> IsStillWanted:
    """The same answer, for the different reason that there is no row at all.

    Two helpers rather than one, because the cases are two: a walk that was
    stopped, and a walk whose incident was taken out from under it.
    """
    def still_wanted(dont_care_incident_id: str) -> bool:
        return False

    return still_wanted


def _a_node_returning(updates: dict[str, Any],
                      narration: Narration = DONT_CARE_NARRATION) -> Node:
    """A node standing in for a real one, so the wrapper is tested on what it
    does with a return value rather than on any node's private reasoning."""
    def node(dont_care_state: IncidentState) -> dict[str, Any]:
        return {**updates, "narration": narration}

    return node


def _a_node_that_records_being_run(ran: list[str]) -> Node:
    """A node that says it was reached, for the cases where it must not be."""
    def node(state: IncidentState) -> dict[str, Any]:
        ran.append(state.incident_id)

        return {"proposed_action": None, "narration": DONT_CARE_NARRATION}

    return node


def _an_incident_being_investigated() -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.INVESTIGATING)


def _an_incident_mitigating() -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.MITIGATING,
                         candidates=[a_candidate()],
                         candidate_index=0)


def a_candidate() -> Hypothesis:
    return Hypothesis(incident_id=DONT_CARE_INCIDENT_ID,
                      summary="the monthly-spend flag was switched on",
                      cause_type=CauseType.FEATURE_FLAG_TOGGLE,
                      confidence=0.8,
                      supporting_evidence=[],
                      subject="monthly-spend-feature")


def _the_incident_was_moved_once_to(expected: IncidentStatus,
                                    transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if transition_incident.call_count != 1:
            raise AssertionError(
                f"expected exactly one transition, "
                f"got {transition_incident.call_count}"
            )

        moved_to = transition_incident.call_args.args[1]
        if moved_to is not expected:
            raise AssertionError(
                f"expected a transition to [{expected}], it was to [{moved_to}]"
            )

        return True

    return assertion


def _the_move_was_narrated_as(expected: IncidentStatus,
                              transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        narrating = transition_incident.call_args.kwargs["narrating"]
        if not isinstance(narrating, StatusChanged):
            raise AssertionError(
                f"expected the move to be narrated as a status change, "
                f"it was narrated as [{type(narrating).__name__}]"
            )

        if narrating.to_status is not expected:
            raise AssertionError(
                f"expected the narration to report [{expected}], "
                f"it reported [{narrating.to_status}]"
            )

        return True

    return assertion


def _the_move_was_attributed_to(expected: Actor,
                                transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        attributed_to = transition_incident.call_args.kwargs["actor"]
        if attributed_to is not expected:
            raise AssertionError(
                f"expected the move to be attributed to [{expected}], "
                f"it was attributed to [{attributed_to}]"
            )

        return True

    return assertion


def _the_incident_was_not_moved(transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if transition_incident.call_count != 0:
            raise AssertionError(
                f"expected no transition, got {transition_incident.call_args_list}"
            )

        return True

    return assertion


def _exactly_one_note_said(action: str,
                           result: str,
                           record_note: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if record_note.call_count != 1:
            raise AssertionError(
                f"expected exactly one note, got {record_note.call_count}"
            )

        noted = record_note.call_args.kwargs
        if (noted["action"], noted["result"]) != (action, result):
            raise AssertionError(
                f"expected a note of [{action}] / [{result}], "
                f"got [{noted['action']}] / [{noted['result']}]"
            )

        return True

    return assertion


def _nothing_was_noted(record_note: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if record_note.call_count != 0:
            raise AssertionError(
                f"expected no note, got {record_note.call_args_list}"
            )

        return True

    return assertion


def _the_updates_are(expected: NodeResult) -> Assertion[NodeResult]:
    """Every field, so a narration left in the updates fails here and nowhere
    else - what must not be carried is named by its absence from this."""
    def assertion(updates: NodeResult) -> bool:
        if updates != expected:
            raise AssertionError(
                f"expected the node's updates to be {expected}, got {updates}"
            )

        return True

    return assertion


def _the_updates_carry(field: str, expected: Any) -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        if field not in updates:
            raise AssertionError(
                f"expected the updates to carry [{field}], they carry {sorted(updates)}"
            )

        if updates[field] != expected:
            raise AssertionError(
                f"expected [{field}] to be [{expected}], it was [{updates[field]}]"
            )

        return True

    return assertion


def _the_node_never_ran(ran: list[str]) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if ran:
            raise AssertionError(f"expected the node not to run, it ran for {ran}")

        return True

    return assertion
