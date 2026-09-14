from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_core.events import StatusChanged
from argus_core.models import Actor, Alert, CauseType, Hypothesis, IncidentStatus
from argus_incidents.withdrawal import IsStillWanted
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk import ports
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.narrating import with_status
from orchestrator.walk.state import IncidentState

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

type Node = Callable[[IncidentState], StateDelta]
type NodeResult = dict[str, Any]

SOME_MAX_ROUNDS = 3
DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"
DONT_CARE_NARRATION = Narration(action="dont care")
DONT_CARE_ACTOR = Actor.ORCHESTRATOR


@pytest.fixture
def transition_incident() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.TransitionIncident, instance=True))


@pytest.mark.unit
def test_a_node_that_moved_the_incident_transitions_it_once(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_is_still_wanted())(an_incident_being_investigated)
        ) \
        .then(all_of(
            _the_incident_was_moved_once_to(IncidentStatus.MITIGATING,
                                            transition_incident),
            _the_move_was_narrated_as(IncidentStatus.MITIGATING,
                                      transition_incident)))


@pytest.mark.unit
def test_a_node_that_moved_nothing_writes_no_transition(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_the_incident_was_not_moved(transition_incident))


@pytest.mark.unit
def test_a_node_that_moved_nothing_writes_nothing_at_all(
    transition_incident: MagicMock
) -> None:
    # Work that settles nothing is still work a reader needs to see - and it is
    # said as the node's own published event now, not returned here as free
    # text for this to write down. Narration accompanies a transition and
    # nothing else, so a node that moved the incident nowhere leaves no row
    # behind however much it had to say.
    Scenario() \
        .given(
            a_gate_refusing_an_action := _a_node_returning(
                {"proposed_action": None},
                narration=Narration(action="dont care", detail="dont care")
            ),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            a_gate_refusing_an_action,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_the_incident_was_not_moved(transition_incident))


@pytest.mark.unit
def test_the_narration_never_reaches_the_graphs_state(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_is_still_wanted())(an_incident_mitigating)
        ) \
        .then(_the_updates_are({"proposed_action": None}))


@pytest.mark.unit
def test_the_derived_status_is_returned_with_the_nodes_work(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_is_still_wanted())(an_incident_being_investigated)
        ) \
        .then(all_of(
            _the_updates_carry("status", IncidentStatus.MITIGATING),
            _the_updates_carry("candidate_index", 0))
        )


@pytest.mark.unit
def test_a_withdrawn_incident_stops_the_node_before_it_runs(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            still_wanted=_the_incident_was_withdrawn())(an_incident_mitigating)
        ) \
        .then(all_of(
            _the_node_never_ran(ran),
            _the_updates_are({"status": IncidentStatus.WITHDRAWN}),
            _the_incident_was_not_moved(transition_incident))
        )


@pytest.mark.unit
def test_an_incident_nobody_has_is_not_walked_either(
    transition_incident: MagicMock
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
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
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
    does with a return value rather than on any node's private reasoning.

    Still a mapping at the call sites, because what a case here says is "a node
    that changed these fields" and naming them is the readable way to say it.
    `StateDelta` forbids extras, so a field misspelt in one of those mappings
    fails here rather than being dropped in silence.
    """
    def node(dont_care_state: IncidentState) -> StateDelta:
        return StateDelta(**updates, narration=narration)

    return node


def _a_node_that_records_being_run(ran: list[str]) -> Node:
    """A node that says it was reached, for the cases where it must not be."""
    def node(state: IncidentState) -> StateDelta:
        ran.append(state.incident_id)

        return StateDelta(proposed_action=None, narration=DONT_CARE_NARRATION)

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
                f"Expected exactly one transition, "
                f"got {transition_incident.call_count}."
            )

        moved_to = transition_incident.call_args.args[1]
        if moved_to is not expected:
            raise AssertionError(
                f"Expected a transition to [{expected}], it was to [{moved_to}]."
            )

        return True

    return assertion


def _the_move_was_narrated_as(expected: IncidentStatus,
                              transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        narrating = transition_incident.call_args.kwargs["narrating"]
        if not isinstance(narrating, StatusChanged):
            raise AssertionError(
                f"Expected the move to be narrated as a status change, "
                f"it was narrated as [{type(narrating).__name__}]."
            )

        if narrating.to_status is not expected:
            raise AssertionError(
                f"Expected the narration to report [{expected}], "
                f"it reported [{narrating.to_status}]."
            )

        return True

    return assertion


def _the_incident_was_not_moved(transition_incident: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if transition_incident.call_count != 0:
            raise AssertionError(
                f"Expected no transition, got {transition_incident.call_args_list}."
            )

        return True

    return assertion


def _the_updates_are(expected: NodeResult) -> Assertion[NodeResult]:
    """Every field, so a narration left in the updates fails here and nowhere
    else - what must not be carried is named by its absence from this."""
    def assertion(updates: NodeResult) -> bool:
        if updates != expected:
            raise AssertionError(
                f"Expected the node's updates to be {expected}, got {updates}."
            )

        return True

    return assertion


def _the_updates_carry(field: str, expected: Any) -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        if field not in updates:
            raise AssertionError(
                f"Expected the updates to carry [{field}], they carry {sorted(updates)}."
            )

        if updates[field] != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], it was [{updates[field]}]."
            )

        return True

    return assertion


def _the_node_never_ran(ran: list[str]) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if ran:
            raise AssertionError(f"Expected the node not to run, it ran for {ran}.")

        return True

    return assertion
