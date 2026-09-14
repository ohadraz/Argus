from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_core.events import ActionRefused, IncidentEvent
from argus_core.models.action import Action
from argus_core.models.alert import Alert
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.refusal import Refusal
from argus_core.models.undo_descriptor import UndoDescriptor
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk import ports
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.gating import route_after_gate, tier_gate_node
from orchestrator.walk.routes import MITIGATING_ROUTE, NEXT_CANDIDATE_ROUTE

from ..framework.builders import a_determined_hypothesis, a_random_id, an_incident_state

"""The one thing standing between a proposed action and the call that performs it.

A guarantee enforced by the code it constrains is a convention, not a guarantee,
so the check lives here rather than inside the agent that does the write: an
action with no undo descriptor is not reversible however it is labelled.

A rejection is about *this* action, not about the incident. The explanations
after it on the list may be perfectly reversible, so the gate clears the action,
says why, and moves the incident nowhere - whether anything follows is decided
one node further on, in one place.
"""


DONT_CARE_FLAG = "dont-care-flag"


@pytest.fixture
def record_outcome() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordOutcome, instance=True))


@pytest.mark.unit
def test_the_gate_lets_an_action_carrying_an_undo_descriptor_through(
    record_outcome: MagicMock
) -> None:
    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident, record_outcome=record_outcome)) \
        .then(all_of(_the_gate_changed_nothing(),
                     _no_outcome_was_recorded(record_outcome)))


@pytest.mark.unit
def test_the_gate_rejects_an_action_whose_undo_descriptor_is_empty(
    record_outcome: MagicMock
) -> None:
    # The guarantee cannot rest on the agent that performs the write also
    # policing itself: a reversible action is only reversible if something
    # recorded how to reverse it, and this is the last point at which that can
    # still be checked for free.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_gated_incident := _a_mitigating_incident(
                proposing=_an_action_with_no_undo_descriptor()
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(Refusal.NOT_REVERSIBLE, published)))


@pytest.mark.unit
def test_the_gate_rejects_an_incident_with_no_proposed_action(
    record_outcome: MagicMock
) -> None:
    # The walk reaches the gate whether or not a proposal was made: with no
    # candidate there is nothing to answer, and the refusal is still the only
    # account of why this attempt ended.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(a_gated_incident := _a_mitigating_incident()) \
        .when(lambda: tier_gate_node(a_gated_incident,
                                     record_outcome=record_outcome,
                                     publisher=published.append)) \
        .then(all_of(_the_action_was_cleared(),
                     _the_incident_was_moved_nowhere(),
                     _nothing_was_narrated(),
                     _the_refusal_was_published(Refusal.NO_REVERSIBLE_ACTION,
                                                published)))


@pytest.mark.unit
def test_a_candidate_the_gate_refused_is_recorded_as_never_having_been_tried(
    record_outcome: MagicMock
) -> None:
    # A refused action is not the candidate being wrong - it is the candidate
    # never having been put to the question, and its row has to say so. The
    # reason is written down here because this is the only place that knows it:
    # the rejection clears the action on the way out.
    Scenario() \
        .given(
            some_candidate := a_determined_hypothesis(a_random_id()),
            a_gated_incident := _a_mitigating_incident(
                proposing=_an_action_with_no_undo_descriptor(), about=some_candidate
            )
        ) \
        .when(lambda: tier_gate_node(a_gated_incident, record_outcome=record_outcome)) \
        .then(_the_candidate_was_recorded_as_untried(some_candidate,
                                                     "not reversible",
                                                     record_outcome))


@pytest.mark.unit
def test_an_admitted_action_is_routed_to_the_node_that_performs_it() -> None:
    Scenario() \
        .given(
            an_admitted_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: route_after_gate(an_admitted_incident)) \
        .then(_the_route_is(MITIGATING_ROUTE))


@pytest.mark.unit
def test_a_rejected_action_is_handed_to_the_walk() -> None:
    # The gate clears the action it refused rather than marking the incident
    # escalated: the refusal is about this action, and the explanations after
    # it on the list may be perfectly reversible. Whether anything follows is
    # the walk's decision, made in one place - so a rejected action reaches no
    # state-changing call, and no premature ending either.
    Scenario() \
        .given(a_rejected_incident := _a_mitigating_incident()) \
        .when(lambda: route_after_gate(a_rejected_incident)) \
        .then(_the_route_is(NEXT_CANDIDATE_ROUTE))


def _a_mitigating_incident(proposing: Action | None = None,
                           about: Hypothesis | None = None) -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about or a_determined_hypothesis(state.incident_id),
            "proposed_action": proposing
        }
    )


def _an_action_with_an_undo_descriptor() -> Action:
    return Action(action_type="revert-feature-flag",
                  flag=DONT_CARE_FLAG,
                  enabled=False,
                  undo_descriptor=UndoDescriptor(flag=DONT_CARE_FLAG, was_enabled=True))


def _an_action_with_no_undo_descriptor() -> Action:
    return Action(action_type="revert-feature-flag",
                  flag=DONT_CARE_FLAG,
                  enabled=False,
                  undo_descriptor=None)


def _the_gate_changed_nothing() -> Assertion[StateDelta]:
    """An admitted action leaves the state exactly as it arrived. Anything at
    all here would be the gate deciding something, and the gate decides only
    whether to refuse."""
    def assertion(updates: StateDelta) -> bool:
        if updates.model_fields_set:
            raise AssertionError(
                f"Expected the gate to change nothing, it set "
                f"{sorted(updates.model_fields_set)}."
            )

        return True

    return assertion


def _no_outcome_was_recorded(record_outcome: MagicMock) -> Assertion[StateDelta]:
    """The candidate is about to be put to the question, so nothing is known
    about it yet - a row marked with an outcome here would be marked before the
    experiment that produces one."""
    def assertion(dont_care_result: StateDelta) -> bool:
        if record_outcome.call_count != 0:
            raise AssertionError(
                f"Expected no outcome to be recorded, got "
                f"{record_outcome.call_args_list}."
            )

        return True

    return assertion


def _the_action_was_cleared() -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if updates.proposed_action is not None:
            raise AssertionError(
                f"Expected the refused action to be cleared, the gate returned "
                f"{updates.proposed_action!r}."
            )

        return True

    return assertion


def _the_incident_was_moved_nowhere() -> Assertion[StateDelta]:
    """A rejection ends this attempt, not the incident: `mitigating` before and
    after, so the gate names no status at all."""
    def assertion(updates: StateDelta) -> bool:
        if "status" in updates.model_fields_set:
            raise AssertionError(
                f"Expected the gate to name no status, it named "
                f"[{updates.status}]."
            )

        return True

    return assertion


def _the_refusal_was_published(expected: Refusal,
                               published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The gate's own account of what it would not allow.

    Published by this node rather than returned for somebody else to write
    down, the way the proposal publishes the history it rested on: the gate is
    the only place that knows a refusal happened, and a refusal that travelled
    as free text would reach the page as a sentence nobody can count.
    """
    def assertion(dont_care_updates: StateDelta) -> bool:
        refusals = [event for event in published if isinstance(event, ActionRefused)]

        if not refusals:
            raise AssertionError(
                f"Expected the refusal to be published, got "
                f"{[event.kind for event in published]}."
            )

        if refusals[0].refusal is not expected:
            raise AssertionError(
                f"Expected [{expected}] published, got [{refusals[0].refusal}]."
            )

        return True

    return assertion


def _nothing_was_narrated() -> Assertion[StateDelta]:
    """The gate says nothing through the walk's narration.

    Narration is how a node that *moved* the incident accounts for the move,
    and this one moves it nowhere. Returning a sentence here is what used to
    route the refusal into a second, untyped account of the same event.
    """
    def assertion(updates: StateDelta) -> bool:
        if updates.narration is not None:
            raise AssertionError(
                f"Expected the gate to narrate nothing, it said "
                f"[{updates.narration.action}]."
            )

        return True

    return assertion


def _the_candidate_was_recorded_as_untried(candidate: Hypothesis,
                                           reason: str,
                                           record_outcome: MagicMock
                                           ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if record_outcome.call_count != 1:
            raise AssertionError(
                f"Expected exactly one outcome to be recorded, got "
                f"{record_outcome.call_count}."
            )

        recorded_about = record_outcome.call_args.args[0]
        if recorded_about != candidate.id:
            raise AssertionError(
                f"Expected the outcome to be about [{candidate.id}], it was "
                f"about [{recorded_about}]."
            )

        recorded = record_outcome.call_args.kwargs
        if recorded["tested"] is not False:
            raise AssertionError(
                "Expected the candidate to be recorded as never having been tried."
            )

        if reason not in recorded["result"]:
            raise AssertionError(
                f"Expected the reason to say [{reason}], it said "
                f"[{recorded['result']}]."
            )

        return True

    return assertion


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"Expected the route [{expected}], got [{route}].")\

        return True

    return assertion
