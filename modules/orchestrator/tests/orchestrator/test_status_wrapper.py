from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_core.events import IncidentEvent, Publisher, StatusChanged, nobody
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from orchestrator import graph
from orchestrator.graph import Narration, with_status

"""The one place a status is persisted, and the one place it is published.

Nodes do their work and say what they did; this decides where the incident
stands and writes it down. Keeping that in a wrapper rather than in each node is
what makes "a status is written only when the incident enters it" a property of
the graph instead of a rule five nodes have to remember - and the rule was
already being forgotten.
"""

SOME_MAX_ROUNDS = 3
_AN_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
_SOME_INCIDENT_ID = "buki-123"


@pytest.fixture
def transition_incident() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.TransitionIncident, instance=True))


@pytest.fixture
def record_note() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordNote, instance=True))


@pytest.mark.unit
def test_a_node_that_moved_the_incident_transitions_it_once(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    published: list[IncidentEvent] = []
    an_investigation_that_found_something = _a_node_returning(
        {"candidates": [_a_candidate()], "candidate_index": 0}
    )

    _run(
        an_investigation_that_found_something,
        _an_incident_being_investigated(),
        transition_incident=transition_incident,
        record_note=record_note,
        publisher=published.append,
    )

    transition_incident.assert_called_once()
    assert transition_incident.call_args.args[1] is IncidentStatus.MITIGATING
    moved = [event for event in published if isinstance(event, StatusChanged)]
    assert [event.to_status for event in moved] == [IncidentStatus.MITIGATING]
    record_note.assert_not_called()


@pytest.mark.unit
def test_a_node_that_moved_nothing_writes_no_transition_and_publishes_nothing(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # The guarantee the whole change exists for. A status set here and
    # overwritten one node later is a claim about the incident that the timeline
    # cannot take back, so it is never written in the first place.
    published: list[IncidentEvent] = []
    a_gate_refusing_an_action = _a_node_returning(
        {"proposed_action": None},
        narration=Narration(action="action rejected at the tier gate"),
    )

    _run(
        a_gate_refusing_an_action,
        _an_incident_mitigating(),
        transition_incident=transition_incident,
        record_note=record_note,
        publisher=published.append,
    )

    transition_incident.assert_not_called()
    assert published == []


@pytest.mark.unit
def test_a_node_that_moved_nothing_still_says_what_it_did(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Work that settles nothing is still work a human reading the incident needs
    # to see. Silence here is how a rejected action became indistinguishable
    # from an action that was never proposed.
    a_gate_refusing_an_action = _a_node_returning(
        {"proposed_action": None},
        narration=Narration(
            action="action rejected at the tier gate",
            result="the proposed action carries no undo descriptor",
        ),
    )

    _run(
        a_gate_refusing_an_action,
        _an_incident_mitigating(),
        transition_incident=transition_incident,
        record_note=record_note,
    )

    record_note.assert_called_once()
    assert record_note.call_args.kwargs["action"] == "action rejected at the tier gate"
    assert record_note.call_args.kwargs["result"] == (
        "the proposed action carries no undo descriptor"
    )


@pytest.mark.unit
def test_the_actor_on_a_row_is_the_agent_the_node_was_registered_as(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Which agent a node belongs to is fixed when the graph is built. It was
    # being repeated inside every call as a constant, which is one more thing a
    # node could get wrong about itself.
    a_node_finding_a_candidate = _a_node_returning(
        {"candidates": [_a_candidate()], "candidate_index": 0}
    )

    _run(
        a_node_finding_a_candidate,
        _an_incident_being_investigated(),
        actor=Actor.INVESTIGATOR,
        transition_incident=transition_incident,
        record_note=record_note,
    )

    assert transition_incident.call_args.kwargs["actor"] is Actor.INVESTIGATOR


@pytest.mark.unit
def test_the_narration_never_reaches_the_graphs_state(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # What a node said is written to the timeline and dropped. Left in the
    # updates it would become a field of `IncidentState`, checkpointed forever,
    # describing whichever node happened to run last.
    a_narrating_node = _a_node_returning(
        {"proposed_action": None}, narration=Narration(action="dont care")
    )

    updates = _run(
        a_narrating_node,
        _an_incident_mitigating(),
        transition_incident=transition_incident,
        record_note=record_note,
    )

    assert "narration" not in updates
    assert updates == {"proposed_action": None}


@pytest.mark.unit
def test_the_derived_status_is_returned_with_the_nodes_work(
    transition_incident: MagicMock, record_note: MagicMock
) -> None:
    # Routing reads the status off the state, as it always has. What changed is
    # who put it there.
    an_investigation_that_found_something = _a_node_returning(
        {"candidates": [_a_candidate()], "candidate_index": 0}
    )

    updates = _run(
        an_investigation_that_found_something,
        _an_incident_being_investigated(),
        transition_incident=transition_incident,
        record_note=record_note,
    )

    assert updates["status"] is IncidentStatus.MITIGATING
    assert updates["candidate_index"] == 0


def _run(
    node: Any,
    state: IncidentState,
    transition_incident: MagicMock,
    record_note: MagicMock,
    actor: Actor = Actor.ORCHESTRATOR,
    publisher: Publisher = nobody,
) -> dict[str, Any]:
    wrapped = with_status(
        node,
        actor,
        SOME_MAX_ROUNDS,
        transition_incident=transition_incident,
        record_note=record_note,
        publisher=publisher,
    )

    return wrapped(state)


_DONT_CARE_NARRATION = Narration(action="dont care")


def _a_node_returning(
    updates: dict[str, Any], narration: Narration = _DONT_CARE_NARRATION
) -> Any:
    """A node standing in for a real one, so the wrapper is tested on what it
    does with a return value rather than on any node's private reasoning."""
    def node(_state: IncidentState) -> dict[str, Any]:
        return {**updates, "narration": narration}

    return node


def _an_incident_being_investigated() -> IncidentState:
    return IncidentState(
        incident_id=_SOME_INCIDENT_ID, alert=_AN_ALERT, status=IncidentStatus.INVESTIGATING
    )


def _an_incident_mitigating() -> IncidentState:
    return IncidentState(
        incident_id=_SOME_INCIDENT_ID,
        alert=_AN_ALERT,
        status=IncidentStatus.MITIGATING,
        candidates=[_a_candidate()],
        candidate_index=0,
    )


def _a_candidate() -> Hypothesis:
    return Hypothesis(
        incident_id=_SOME_INCIDENT_ID,
        summary="the monthly-spend flag was switched on",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.8,
        supporting_evidence=[],
        subject="monthly-spend-feature",
    )
