from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from agent_mitigation import take_action
from agent_mitigation.tools import fetch_recent_flag_changes
from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of
from orchestrator import graph
from orchestrator.graph import (
    investigator_node,
    mitigation_node,
    mitigation_proposal_node,
    tier_gate_node,
)

from ..framework.assertions import assert_that
from ..framework.builders import (
    a_below_threshold_confidence,
    a_determined_hypothesis,
    a_high_enough_confidence,
    an_incident_state,
    an_undetermined_hypothesis,
)


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_investigator.investigate))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordHypothesis, instance=True))


@pytest.fixture
def transition_incident() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.TransitionIncident, instance=True))


@pytest.fixture
def record_action() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordAction, instance=True))


@pytest.fixture
def fetch_flag_changes() -> MagicMock:
    return cast(MagicMock, create_autospec(fetch_recent_flag_changes))


@pytest.fixture
def take() -> MagicMock:
    return cast(MagicMock, create_autospec(take_action))


@pytest.mark.unit
def test_investigator_node_high_confidence_routes_to_mitigating_and_persists(
    investigate: MagicMock, record_hypothesis: MagicMock, transition_incident: MagicMock
) -> None:
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    a_confident_hypothesis = a_determined_hypothesis(
        some_incident_id, a_high_enough_confidence()
    )

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, a_confident_hypothesis)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis,
                                        transition_incident=transition_incident)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": a_confident_hypothesis,
                    "confidence": a_confident_hypothesis.confidence,
                    "status": IncidentStatus.MITIGATING
                }
            ),
            assert_that(record_hypothesis).was_called_with(a_confident_hypothesis),
            assert_that(transition_incident).was_called_with(
                some_incident_id,
                IncidentStatus.MITIGATING,
                actor=Actor.INVESTIGATOR,
                action="hypothesis formed",
                result=a_confident_hypothesis.summary,
                confidence=a_confident_hypothesis.confidence,
            ),
        ))


@pytest.mark.unit
def test_investigator_node_low_confidence_routes_to_escalated_and_persists(
    investigate: MagicMock, record_hypothesis: MagicMock, transition_incident: MagicMock
) -> None:
    # A cause was named, just not confidently enough to act on. The timeline
    # says a hypothesis was formed, because one was - the escalation is about
    # the score, not about the evidence running out.
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    a_doubtful_hypothesis = a_determined_hypothesis(
        some_incident_id, a_below_threshold_confidence()
    )

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, a_doubtful_hypothesis)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis,
                                        transition_incident=transition_incident)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": a_doubtful_hypothesis,
                    "confidence": a_doubtful_hypothesis.confidence,
                    "status": IncidentStatus.ESCALATED
                }
            ),
            assert_that(record_hypothesis).was_called_with(a_doubtful_hypothesis),
            assert_that(transition_incident).was_called_with(
                some_incident_id,
                IncidentStatus.ESCALATED,
                actor=Actor.INVESTIGATOR,
                action="hypothesis formed",
                result=a_doubtful_hypothesis.summary,
                confidence=a_doubtful_hypothesis.confidence,
            ),
        ))


@pytest.mark.unit
def test_investigator_node_undetermined_cause_routes_to_escalated_and_persists(
    investigate: MagicMock, record_hypothesis: MagicMock, transition_incident: MagicMock
) -> None:
    # The loop reached the end of what it could read and named nothing. The
    # timeline has to say *that*, not "hypothesis formed" - a human picking
    # the incident up needs to know whether to look for more evidence or to
    # doubt the one on file.
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    a_hypothesis_with_no_cause = an_undetermined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, a_hypothesis_with_no_cause)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis,
                                        transition_incident=transition_incident)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": a_hypothesis_with_no_cause,
                    "confidence": None,
                    "status": IncidentStatus.ESCALATED
                }
            ),
            assert_that(record_hypothesis).was_called_with(a_hypothesis_with_no_cause),
            assert_that(transition_incident).was_called_with(
                some_incident_id,
                IncidentStatus.ESCALATED,
                actor=Actor.INVESTIGATOR,
                action="insufficient evidence",
                result=a_hypothesis_with_no_cause.summary,
                confidence=None,
            ),
        ))


@pytest.mark.unit
def test_the_proposal_node_proposes_an_action_for_the_flag_that_changed(
    fetch_flag_changes: MagicMock
) -> None:
    # The node reads the provider and hands the choice to the agent; nothing
    # mutating happens here, which is what leaves room for the gate between
    # this node and the one that acts.
    some_flag = "monthly-spend-feature"
    a_mitigating_incident = _a_mitigating_incident()
    fetch_flag_changes.return_value = [_an_enabling_of(some_flag)]

    result = mitigation_proposal_node(
        a_mitigating_incident, fetch_flag_changes=fetch_flag_changes
    )

    proposed = result["proposed_action"]
    assert proposed is not None
    assert proposed.flag == some_flag
    assert proposed.enabled is False


@pytest.mark.unit
def test_the_proposal_node_proposes_nothing_when_the_provider_cannot_be_read(
    fetch_flag_changes: MagicMock
) -> None:
    # "Nothing changed" and "I could not find out" both mean there is no action
    # to take, and neither is a reason to crash the graph - the incident goes
    # to a human, which is what an unreachable provider warrants.
    a_mitigating_incident = _a_mitigating_incident()
    fetch_flag_changes.side_effect = RuntimeError("the provider could not be reached")

    result = mitigation_proposal_node(
        a_mitigating_incident, fetch_flag_changes=fetch_flag_changes
    )

    assert result["proposed_action"] is None


@pytest.mark.unit
def test_the_gate_lets_an_action_carrying_an_undo_descriptor_through(
    transition_incident: MagicMock
) -> None:
    a_gated_incident = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    result = tier_gate_node(a_gated_incident, transition_incident=transition_incident)

    assert result == {}
    assert transition_incident.call_count == 0


@pytest.mark.unit
def test_the_gate_rejects_an_action_whose_undo_descriptor_is_empty(
    transition_incident: MagicMock
) -> None:
    # The guarantee cannot rest on the agent that performs the write also
    # policing itself: a reversible action is only reversible if something
    # recorded how to reverse it, and this is the last point at which that can
    # still be checked for free.
    a_gated_incident = _a_mitigating_incident(proposing=_an_action_with_no_undo_descriptor())

    result = tier_gate_node(a_gated_incident, transition_incident=transition_incident)

    assert result == {"status": IncidentStatus.ESCALATED}
    assert transition_incident.call_args.args[1] is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_the_gate_rejects_an_incident_with_no_proposed_action(
    transition_incident: MagicMock
) -> None:
    a_gated_incident = _a_mitigating_incident()

    result = tier_gate_node(a_gated_incident, transition_incident=transition_incident)

    assert result == {"status": IncidentStatus.ESCALATED}
    assert transition_incident.call_args.args[1] is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_a_confirmed_action_resolves_the_incident(
    take: MagicMock, record_action: MagicMock, transition_incident: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.CONFIRMED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             transition_incident=transition_incident)

    assert result["status"] is IncidentStatus.RESOLVED
    assert result["action_outcome"] == "confirmed"


@pytest.mark.unit
def test_a_refuted_action_routes_to_fixing(
    take: MagicMock, record_action: MagicMock, transition_incident: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.REFUTED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             transition_incident=transition_incident)

    assert result["status"] is IncidentStatus.FIXING


@pytest.mark.unit
def test_an_escalated_outcome_never_resolves_the_incident(
    take: MagicMock, record_action: MagicMock, transition_incident: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.ESCALATED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             transition_incident=transition_incident)

    assert result["status"] is IncidentStatus.ESCALATED


@pytest.mark.unit
def test_the_action_row_records_the_undo_descriptor_the_write_returned(
    take: MagicMock, record_action: MagicMock, transition_incident: MagicMock
) -> None:
    # The descriptor the write tier returned, not the one proposed: it is the
    # record of what actually changed, and it is what a human reading the
    # incident afterwards would have to act on.
    some_undo_descriptor = {
        "tool": "set_feature_flag",
        "flag": "monthly-spend-feature",
        "environment": "production",
        "was_enabled": False,
    }
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.CONFIRMED, undo_descriptor=some_undo_descriptor)

    mitigation_node(an_action_taking_incident,
                    take=take,
                    record_action=record_action,
                    transition_incident=transition_incident)

    assert record_action.call_args.kwargs["undo_descriptor"] == some_undo_descriptor


DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"


def _an_investigating_incident() -> IncidentState:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    return an_incident_state(some_alert, IncidentStatus.INVESTIGATING)


def _a_mitigating_incident(proposing: Action | None = None) -> IncidentState:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": a_determined_hypothesis(
                state.incident_id, a_high_enough_confidence()
            ),
            "proposed_action": proposing,
        }
    )


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)


def _an_action_with_an_undo_descriptor() -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor={"tool": "set_feature_flag", "flag": DONT_CARE_FLAG,
                         "was_enabled": True},
    )


def _an_action_with_no_undo_descriptor() -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor={},
    )


def _an_outcome(verdict: Verdict,
                undo_descriptor: dict[str, object] | None = None) -> Outcome:
    return Outcome(
        verdict=verdict,
        detail="dont care",
        undo_descriptor=undo_descriptor or {},
    )


def _investigation_returned(investigate: MagicMock, hypothesis: Hypothesis) -> None:
    investigate.return_value = hypothesis
