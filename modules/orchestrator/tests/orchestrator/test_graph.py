from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of
from orchestrator import graph
from orchestrator.graph import investigator_node

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


def _an_investigating_incident() -> IncidentState:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    return an_incident_state(some_alert, IncidentStatus.INVESTIGATING)


def _investigation_returned(investigate: MagicMock, hypothesis: Hypothesis) -> None:
    investigate.return_value = hypothesis
