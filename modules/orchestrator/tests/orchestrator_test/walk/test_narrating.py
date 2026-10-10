"""The one place a status is persisted, and the one place it is published.

Nodes do their work and say what they did; this decides where the incident
stands and writes it down. Keeping that in a wrapper rather than in each node is
what makes "a status is written only when the incident enters it" a property of
the graph instead of a rule five nodes have to remember - and the rule was
already being forgotten.

It is also where the walk finds out a person has ended the incident. Every node
the graph runs passes through here first, so one question asked in one place
stops all of them - and asked before the node rather than after, because a node
that has already toggled a flag cannot be stopped by anything this wrapper does
with its return value.

Two endings, and one node that answers to only one of them. A withdrawal stops
every node; a resolution stops every node but the postmortem, which is what the
person who reported the incident over is owed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from argus_core.events import StatusChanged
from argus_core.models import Actor, Alert, FailureMode, Hypothesis, IncidentStatus
from argus_incidents.ending import EndedByAPerson
from argus_incidents.waiting import WaitForPeople
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.narrating import with_status
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import (
    a_person_ended_the_incident,
    nobody_ended_the_incident,
)

type Node = Callable[[IncidentState], StateDelta]
type NodeResult = dict[str, Any]

SOME_MAX_ROUNDS = 3
DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "buki-123"
DONT_CARE_NARRATION = Narration(action="dont care")
DONT_CARE_ACTOR = Actor.ORCHESTRATOR
# What the one node that runs after a resolution stops for.
ONLY_A_WITHDRAWAL = frozenset({IncidentStatus.WITHDRAWN})


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
            ended_by_a_person=nobody_ended_the_incident())(an_incident_being_investigated)
        ) \
        .then(all_of(
            _the_incident_was_moved_once_to(IncidentStatus.MITIGATING,
                                            transition_incident),
            _the_move_was_narrated_as(IncidentStatus.MITIGATING,
                                      transition_incident)))


@pytest.mark.unit
def test_a_move_is_logged_with_the_reason_it_was_made(
    transition_incident: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    # Every move the walk makes passes through here, so this one line is the
    # walk's whole account of where it went and why - an escalation, another
    # round, a fix - without a line of its own in each node that decided it.
    some_narration = Narration(action="the monthly-spend flag looks to blame")

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            an_investigation_that_found_something := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}, some_narration
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            an_investigation_that_found_something,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=nobody_ended_the_incident())(an_incident_being_investigated)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.narrating", logging.INFO,
                                  "status changed",
                                  values={"from_status": IncidentStatus.INVESTIGATING,
                                          "to_status": IncidentStatus.MITIGATING,
                                          "reason": some_narration.said()})
        )


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
            ended_by_a_person=nobody_ended_the_incident())(an_incident_mitigating)
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
            ended_by_a_person=nobody_ended_the_incident())(an_incident_mitigating)
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
            ended_by_a_person=nobody_ended_the_incident())(an_incident_mitigating)
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
            ended_by_a_person=nobody_ended_the_incident())(an_incident_being_investigated)
        ) \
        .then(all_of(
            the_updates_carry("status", IncidentStatus.MITIGATING),
            the_updates_carry("candidate_index", 0))
        )


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_an_incident_a_person_ended_stops_the_node_before_it_runs(
    transition_incident: MagicMock, ending: IncidentStatus
) -> None:
    # Before, not after. A node that has already toggled a flag cannot be
    # stopped by anything done with its return value, so the question is asked
    # while there is still an answer worth having - and a resolution is as much
    # a reason not to act as a withdrawal is.
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
            ended_by_a_person=a_person_ended_the_incident(ending))(an_incident_mitigating)
        ) \
        .then(all_of(
            _the_node_never_ran(ran),
            _the_updates_are({"status": ending}),
            _the_incident_was_not_moved(transition_incident))
        )


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_a_node_that_finished_after_a_person_ended_the_incident_stops_the_walk(
    transition_incident: MagicMock, ending: IncidentStatus
) -> None:
    # Ended while the node was running, so asking before it was too early to
    # know. The row refused the move, and the walk has to hear that refusal for
    # what it is - and for which ending it was, because a resolution goes on to
    # the postmortem and a withdrawal goes nowhere.
    Scenario() \
        .given(
            calling(lambda: transition_incident.configure_mock(return_value=False)),
            an_investigation_that_found_something := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            an_investigation_that_found_something,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_refused_because_it_was_ended(ending)
        )(an_incident_being_investigated)) \
        .then(
            the_updates_carry("status", ending)
        )


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_a_node_that_moved_nothing_while_a_person_ended_the_incident_stops_the_walk(
    transition_incident: MagicMock, ending: IncidentStatus
) -> None:
    # A step that stopped because a person ended the incident hands back
    # nothing, so there is no move for the row to refuse and nothing for the
    # router to read as a stop. Asked once more after the node, the walk hears
    # the ending anyway - and writes nothing, because the row already says it.
    Scenario() \
        .given(
            a_node_that_stopped := _a_node_returning({}),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            a_node_that_stopped,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_ended_while_the_node_ran(ending)
        )(an_incident_being_investigated)) \
        .then(all_of(
            the_updates_carry("status", ending),
            _the_incident_was_not_moved(transition_incident)
        ))


@pytest.mark.unit
def test_the_node_that_runs_after_a_resolution_runs_on_a_resolved_incident(
    transition_incident: MagicMock
) -> None:
    # The postmortem. A person reporting the incident over is owed the write-up,
    # so a resolution does not stop it - and nothing it returns may move the
    # incident off the status the person gave it.
    ran: list[str] = []

    Scenario() \
        .given(
            the_write_up := _a_node_that_records_being_run(ran),
            a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED)
        ) \
        .when(lambda: with_status(
            the_write_up,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=a_person_ended_the_incident(IncidentStatus.RESOLVED),
            stops_for=ONLY_A_WITHDRAWAL
        )(a_resolved_incident)) \
        .then(all_of(
            _the_node_ran(ran),
            _the_updates_are({"proposed_action": None}),
            _the_incident_was_not_moved(transition_incident)
        ))


@pytest.mark.unit
def test_the_node_that_runs_after_a_resolution_still_stops_for_a_withdrawal(
    transition_incident: MagicMock
) -> None:
    # The person who took the incident back is not waiting to be told what
    # Argus made of it.
    ran: list[str] = []

    Scenario() \
        .given(
            the_write_up := _a_node_that_records_being_run(ran),
            an_incident_mitigating := _an_incident_mitigating()
        ) \
        .when(lambda: with_status(
            the_write_up,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=a_person_ended_the_incident(IncidentStatus.WITHDRAWN),
            stops_for=ONLY_A_WITHDRAWAL
        )(an_incident_mitigating)) \
        .then(all_of(
            _the_node_never_ran(ran),
            _the_updates_are({"status": IncidentStatus.WITHDRAWN})
        ))


@pytest.mark.unit
def test_the_walk_waits_for_people_once_a_step_is_done(
    transition_incident: MagicMock
) -> None:
    # After the step and not before the next, so the press the wait is for is
    # heard before the next step is chosen - and that step is never entered.
    # Here because every node passes through here: no step follows another
    # while a person is being asked to confirm.
    happened: list[str] = []

    Scenario() \
        .given(an_incident_being_investigated := _an_incident_being_investigated()) \
        .when(lambda: with_status(
            _a_node_noting(happened),
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=nobody_ended_the_incident(),
            wait_for_people=_a_wait_noting(happened))(an_incident_being_investigated)
        ) \
        .then(_it_happened_in_order(happened, ["ran", "waited"]))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_an_incident_a_person_ended_while_the_walk_waited_goes_where_the_ending_sends_it(
    ending: IncidentStatus, transition_incident: MagicMock
) -> None:
    # The press is what the wait was for, so it decides where the walk goes
    # next - as an ending heard while the step ran does.
    ended: list[IncidentStatus] = []

    Scenario() \
        .given(an_incident_being_investigated := _an_incident_being_investigated()) \
        .when(lambda: with_status(
            _a_node_noting([]),
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_ended_as_noted(ended),
            wait_for_people=_a_wait_ending_it(ended, ending)
        )(an_incident_being_investigated)) \
        .then(the_updates_carry("status", ending))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED])
def test_a_step_a_person_already_ended_waits_for_nobody(
    ending: IncidentStatus, transition_incident: MagicMock
) -> None:
    # The ending is the answer the wait would have been for.
    happened: list[str] = []

    Scenario() \
        .given(an_incident_being_investigated := _an_incident_being_investigated()) \
        .when(lambda: with_status(
            _a_node_noting(happened),
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=a_person_ended_the_incident(ending),
            wait_for_people=_a_wait_noting(happened))(an_incident_being_investigated)
        ) \
        .then(_it_happened_in_order(happened, []))


@pytest.mark.unit
def test_an_ending_heard_while_the_walk_waited_is_logged(
    transition_incident: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    # The one ending that arrives between steps rather than inside one, said
    # apart from those so an operator can tell a press that was waited for
    # from one that cut a step short.
    ended: list[IncidentStatus] = []

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            _a_node_noting([]),
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_ended_as_noted(ended),
            wait_for_people=_a_wait_ending_it(ended, IncidentStatus.RESOLVED)
        )(an_incident_being_investigated)) \
        .then(one_record_was_logged(caplog, "orchestrator.walk.narrating", logging.INFO,
                                    "ended by a person while the walk waited",
                                    values={"ending": IncidentStatus.RESOLVED}))


@pytest.mark.unit
def test_an_ending_heard_after_a_step_is_logged(
    transition_incident: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing is written for it - the row already says how it ended - so this
    # line is the walk's only account of where it was when it heard.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_node_that_stopped := _a_node_returning({}),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            a_node_that_stopped,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_ended_while_the_node_ran(IncidentStatus.RESOLVED)
        )(an_incident_being_investigated)) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.narrating", logging.INFO,
                                  "ended by a person while a step ran",
                                  values={"from_status": IncidentStatus.INVESTIGATING,
                                          "ending": IncidentStatus.RESOLVED})
        )


@pytest.mark.unit
def test_a_move_the_row_refused_is_logged(
    transition_incident: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    # The other way the walk hears it: the step moved the incident and the row
    # refused, because a person had ended it in the meantime.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            calling(lambda: transition_incident.configure_mock(return_value=False)),
            an_investigation_that_found_something := _a_node_returning(
                {"candidates": [a_candidate()], "candidate_index": 0}
            ),
            an_incident_being_investigated := _an_incident_being_investigated()
        ) \
        .when(lambda: with_status(
            an_investigation_that_found_something,
            SOME_MAX_ROUNDS,
            transition_incident=transition_incident,
            ended_by_a_person=_refused_because_it_was_ended(IncidentStatus.WITHDRAWN)
        )(an_incident_being_investigated)) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.narrating", logging.INFO,
                                  "ended by a person while a step ran",
                                  values={"from_status": IncidentStatus.INVESTIGATING,
                                          "to_status": IncidentStatus.MITIGATING,
                                          "ending": IncidentStatus.WITHDRAWN})
        )


def _ended_while_the_node_ran(ending: IncidentStatus) -> EndedByAPerson:
    """Nobody's when the node began, and `ending` by the time it returned."""
    asked: list[str] = []

    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        asked.append(incident_id)
        return None if len(asked) == 1 else ending

    return ended_by_a_person


def _refused_because_it_was_ended(ending: IncidentStatus) -> EndedByAPerson:
    """Nobody's until the row refused a move, and `ending` when asked why.

    Twice nobody's - before the node and after it - because the case is the
    ending that lands between that second question and the write.
    """
    asked: list[str] = []

    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        asked.append(incident_id)
        return None if len(asked) <= 2 else ending

    return ended_by_a_person


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


def _a_wait_noting(happened: list[str]) -> WaitForPeople:
    def wait(dont_care_incident_id: str, /) -> bool:
        happened.append("waited")

        return True

    return wait


def _a_wait_ending_it(ended: list[IncidentStatus], ending: IncidentStatus) -> WaitForPeople:
    """A wait the person's press arrives during."""
    def wait(dont_care_incident_id: str, /) -> bool:
        ended.append(ending)

        return True

    return wait


def _ended_as_noted(ended: list[IncidentStatus]) -> EndedByAPerson:
    def ended_by_a_person(dont_care_incident_id: str, /) -> IncidentStatus | None:
        return ended[0] if ended else None

    return ended_by_a_person


def _a_node_noting(happened: list[str]) -> Node:
    def node(dont_care_state: IncidentState) -> StateDelta:
        happened.append("ran")

        return StateDelta(proposed_action=None, narration=DONT_CARE_NARRATION)

    return node


def _it_happened_in_order(happened: list[str], expected: list[str]) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if happened != expected:
            raise AssertionError(f"Expected {expected}, in that order, got {happened}.")

        return True

    return assertion


def _an_incident_being_investigated() -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.INVESTIGATING)


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=status)


def _an_incident_mitigating() -> IncidentState:
    return IncidentState(incident_id=DONT_CARE_INCIDENT_ID,
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.MITIGATING,
                         candidates=[a_candidate()],
                         candidate_index=0)


def a_candidate() -> Hypothesis:
    return Hypothesis(incident_id=DONT_CARE_INCIDENT_ID,
                      summary="the monthly-spend flag was switched on",
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
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


def the_updates_carry(field: str, expected: Any) -> Assertion[NodeResult]:
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


def _the_node_ran(ran: list[str]) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if not ran:
            raise AssertionError("Expected the node to run, it never did.")

        return True

    return assertion
