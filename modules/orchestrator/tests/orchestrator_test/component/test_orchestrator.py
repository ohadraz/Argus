from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_investigator import Findings
from agent_mitigation import Action, Outcome, Verdict
from agent_postmortem import PostmortemDocument
from argus_core.config import get_settings
from argus_core.events import Publisher, nobody
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.reading import Reading
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from argus_incidents.withdrawal import IsStillWanted
from argus_testkit import Assertion, Scenario, all_of
from langgraph.checkpoint.memory import MemorySaver
from orchestrator.walk import ports
from orchestrator.walk.assembling import Collaborators
from orchestrator.walk.graph import (
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    TIER_GATE_NODE,
    build_graph,
    recursion_limit,
)

from ..framework.builders import a_random_id

"""The whole walk, through the graph the Orchestrator actually assembles.

Every node is the real one, so what is under test is the module: that a node's
work implies a status, that the status is derived and written once, that the
router reading it reaches a node that exists, and that an incident arrives at
an ending §10 has a name for. Only what lies outside the Orchestrator is
doubled - the agents it delegates to and the repositories it writes through,
both of which it already names as ports.

That leaves no database, no model and no flag provider, so this says the same
thing about the same graph that `e2e` does and says it in a second. What it
cannot say is whether the agents behind those ports are any good; that is
theirs to answer, one module down.
"""

type Walked = tuple[IncidentState, list[str]]

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")

EVERY_ROUND = get_settings().investigation_max_rounds
A_GENEROUS_BUDGET = recursion_limit(max_rounds=EVERY_ROUND, max_candidates=4)


@pytest.fixture
def transition_incident() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.TransitionIncident, instance=True))


@pytest.fixture
def record_note() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordNote, instance=True))


@pytest.fixture
def collaborators(transition_incident: MagicMock,
                  record_note: MagicMock) -> Collaborators:
    """Every port answered by the least eventful thing that can answer it.

    A test then names only the ports its own case turns on, and what it does
    not name cannot be what made it pass.
    """
    return Collaborators(
        investigate=_an_investigation_offering(_a_candidate_blaming(SOME_FLAG)),
        record_hypothesis=lambda dont_care_hypothesis: None,
        fetch_flag_changes=_a_provider_reporting(_an_enabling_of(SOME_FLAG)),
        record_outcome=lambda *dont_care_args, **dont_care_keywords: None,
        take=_an_action_that(Verdict.CONFIRMED),
        record_action=lambda *dont_care_args, **dont_care_keywords: True,
        complete_action=lambda *dont_care_args, **dont_care_keywords: None,
        already_taken=lambda incident_id, hypothesis_id: None,
        claimed_at=lambda incident_id, hypothesis_id: None,
        change_landed=_a_change_that_never_landed(),
        write_postmortem=lambda dont_care_incident: _a_document(),
        record_postmortem=lambda dont_care_incident, dont_care_document: None,
        transition_incident=transition_incident,
        record_note=record_note,
        publisher=nobody,
        recorder=records_nothing,
        still_wanted=_the_incident_is_still_wanted()
    )


@pytest.mark.component
def test_an_action_that_helps_ends_the_incident_in_a_postmortem(
    collaborators: Collaborators
) -> None:
    # The happy path, whole: one investigation, one candidate, one action, and
    # the service recovers. Every node between the alert and the document is
    # reached exactly once, and nothing that ends an incident Argus could not
    # fix is reached at all.
    Scenario() \
        .given(everything_works := collaborators) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), everything_works)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.RESOLVED)))


@pytest.mark.component
def test_an_investigation_that_names_no_cause_reaches_a_human(
    collaborators: Collaborators
) -> None:
    # Nothing to try is not a reason to act. The walk is over before it starts,
    # and it still ends in a postmortem: an incident nobody could explain is
    # one somebody has to read about.
    Scenario() \
        .given(
            an_investigation_finding_nothing := replace(
                collaborators,
                investigate=_an_investigation_offering(_a_candidate_naming_no_cause())
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   an_investigation_finding_nothing)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE, POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_a_refuted_action_is_followed_by_the_next_explanation(
    collaborators: Collaborators
) -> None:
    # The loop, and the reason the walk exists. Being wrong about a correlated
    # change is the ordinary case in an incident, so a refuted action sends the
    # incident back for the next candidate rather than to a human - and the
    # second attempt is a whole attempt, gate included.
    Scenario() \
        .given(
            a_first_answer_that_does_not_hold := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    _a_candidate_blaming(SOME_FLAG), _a_candidate_blaming(ANOTHER_FLAG)
                ),
                fetch_flag_changes=_a_provider_reporting(_an_enabling_of(SOME_FLAG),
                                                         _an_enabling_of(ANOTHER_FLAG)),
                take=_actions_that(Verdict.REFUTED, Verdict.CONFIRMED)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_first_answer_that_does_not_hold)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           NEXT_CANDIDATE_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.RESOLVED)))


@pytest.mark.component
def test_a_walk_with_no_action_left_to_try_ends_at_code_fix_and_a_human(
    collaborators: Collaborators
) -> None:
    # The provider reports nothing that matches the explanation, so no action
    # is proposed and the gate refuses what it was not given. With the last
    # round spent, what remains is a permanent fix - and when Code-Fix has none
    # either, a person.
    Scenario() \
        .given(
            a_provider_reporting_nothing_relevant := replace(
                collaborators, fetch_flag_changes=_a_provider_reporting()
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_on_its_last_round(),
                                   a_provider_reporting_nothing_relevant)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           NEXT_CANDIDATE_NODE,
                           CODEFIX_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_an_incident_nobody_wants_any_more_leaves_the_graph_at_once(
    collaborators: Collaborators,
    transition_incident: MagicMock,
    record_note: MagicMock
) -> None:
    # Asked before the node rather than after: a node that has already toggled
    # a flag cannot be stopped by anything done with its return value. Nothing
    # runs, nothing is written, and the walk leaves the graph from where it
    # stood - the row already says withdrawn, and whoever withdrew it recorded
    # that.
    Scenario() \
        .given(
            an_incident_withdrawn := replace(
                collaborators, still_wanted=_the_incident_was_withdrawn()
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), an_incident_withdrawn)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE),
                     _the_incident_ended(IncidentStatus.WITHDRAWN),
                     _nothing_was_written(transition_incident, record_note)))


def _the_walk_of(incident: IncidentState, collaborators: Collaborators) -> Walked:
    """One incident through the compiled graph, and the nodes it passed.

    The nodes are recorded by wrapping the graph's own stream rather than the
    nodes themselves, so what is asserted is the path LangGraph actually took.
    """
    graph = build_graph(MemorySaver(), collaborators)
    config: Any = {"configurable": {"thread_id": incident.incident_id},
                   "recursion_limit": A_GENEROUS_BUDGET}
    visited: list[str] = []
    final = incident

    for step in graph.stream(incident, config=config, stream_mode="updates"):
        for name, updates in step.items():
            visited.append(name)
            final = final.model_copy(update=updates)

    return final, visited


def _an_incident_just_alerted() -> IncidentState:
    return IncidentState(incident_id=a_random_id(),
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.INVESTIGATING)


def _an_incident_on_its_last_round() -> IncidentState:
    """One round short of the budget, so the investigation about to run is the
    last one this incident gets."""
    return _an_incident_just_alerted().model_copy(update={"rounds": EVERY_ROUND - 1})


def _a_candidate_blaming(flag: str) -> Hypothesis:
    some_confidence = 0.75

    return Hypothesis(incident_id="dont-care",
                      summary=f"the {flag} flag was switched on",
                      cause_type=CauseType.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def _a_candidate_naming_no_cause() -> Hypothesis:
    return Hypothesis(incident_id="dont-care",
                      summary="no cause determined from the evidence retrieved",
                      cause_type=None,
                      confidence=None,
                      supporting_evidence=[Evidence(claim="some log line", at=None)])


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at="2026-08-20T11:05:00Z")


def _an_investigation_offering(*candidates: Hypothesis) -> ports.Investigate:
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing) -> Findings:
        return Findings(
            candidates=[candidate.model_copy(update={"incident_id": incident_id})
                        for candidate in candidates],
            already_read=[]
        )

    return investigate


def _a_provider_reporting(*changes: FlagChange) -> ports.FetchFlagChanges:
    def fetch_flag_changes() -> list[FlagChange]:
        return list(changes)

    return fetch_flag_changes


def _an_action_that(verdict: Verdict) -> ports.TakeAction:
    return _actions_that(verdict)


def _actions_that(*verdicts: Verdict) -> ports.TakeAction:
    """One verdict per attempt, in the order the walk makes them - which is how
    a walk whose first answer is refuted and whose second holds is stated."""
    answers = iter(verdicts)
    last = verdicts[-1]

    def take(action: Action,
             /,
             *,
             still_wanted: Any = None,
             incident_id: str | None = None,
             publisher: Publisher = nobody) -> Outcome:
        return Outcome(verdict=next(answers, last),
                       detail="dont care",
                       undo_descriptor=action.undo_descriptor)

    return take


def _a_change_that_never_landed() -> ports.ChangeLanded:
    def change_landed(flag: str, since: datetime) -> bool | None:
        return False

    return change_landed


def _a_document() -> PostmortemDocument:
    return PostmortemDocument(root_cause=None,
                              executive_summary=None,
                              customer_loss_estimate=None,
                              estimate_currency=None,
                              engineer_minutes=None,
                              responders=None,
                              tokens_spent=None,
                              assumptions=[],
                              checklist_complete=False)


def _the_incident_is_still_wanted() -> IsStillWanted:
    def still_wanted(dont_care_incident_id: str) -> bool:
        return True

    return still_wanted


def _the_incident_was_withdrawn() -> IsStillWanted:
    def still_wanted(dont_care_incident_id: str) -> bool:
        return False

    return still_wanted


def _the_walk_went(*expected: str) -> Assertion[Walked]:
    def assertion(walked: Walked) -> bool:
        dont_care_final, visited = walked
        if visited != list(expected):
            raise AssertionError(
                f"expected the walk to go {list(expected)}, it went {visited}"
            )

        return True

    return assertion


def _the_incident_ended(expected: IncidentStatus) -> Assertion[Walked]:
    def assertion(walked: Walked) -> bool:
        final, dont_care_visited = walked
        if final.status != expected:
            raise AssertionError(
                f"expected the incident to end [{expected}], it ended [{final.status}]"
            )

        return True

    return assertion


def _nothing_was_written(transition_incident: MagicMock,
                         record_note: MagicMock) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if transition_incident.called or record_note.called:
            raise AssertionError(
                f"expected nothing to be written, got "
                f"{transition_incident.call_args_list} and "
                f"{record_note.call_args_list}"
            )

        return True

    return assertion
