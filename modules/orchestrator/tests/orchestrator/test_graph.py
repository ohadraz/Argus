from __future__ import annotations

from functools import partial
from operator import is_not_none
from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of
from orchestrator import graph
from orchestrator.graph import investigator_node

from ..framework.assertions import assert_that
from ..framework.builders import (
    a_below_threshold_confidence,
    a_high_enough_confidence,
    an_incident_state,
)
from ..framework.matchers import matcher


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
    some_hypothesis = "kukibuki hypothesis"
    some_cause_type = CauseType.FEATURE_FLAG_TOGGLE
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_high_confidence = a_high_enough_confidence()
    some_alert = Alert(service=some_service, alert_name=some_alert_name)
    an_inverstigating_incident_state = an_incident_state(some_alert, IncidentStatus.INVESTIGATING)
    some_incident_id = an_inverstigating_incident_state.incident_id
    _investigation_returned = partial(_set_investigate_return_value, investigate)

    Scenario() \
        .given(
            lambda: _investigation_returned(some_hypothesis, some_high_confidence, some_cause_type)
        ) \
        .when(
            result := investigator_node(an_inverstigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis,
                                        transition_incident=transition_incident)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": some_hypothesis, 
                    "confidence": some_high_confidence, 
                    "status": IncidentStatus.MITIGATING
                }
            ),
            assert_that(record_hypothesis).was_called_with(
                some_incident_id, some_hypothesis, some_high_confidence, some_cause_type
            ),
            assert_that(transition_incident).was_called_with(
                some_incident_id,
                IncidentStatus.MITIGATING,
                actor=Actor.INVESTIGATOR,
                action=matcher(is_not_none),
                result=some_hypothesis,
                confidence=some_high_confidence,
            ),
        ))


@pytest.mark.unit
def test_investigator_node_low_confidence_routes_to_escalated_and_persists(
    investigate: MagicMock, record_hypothesis: MagicMock, transition_incident: MagicMock
) -> None:
    some_hypothesis = "stub hypothesis"
    some_low_confidence = a_below_threshold_confidence()
    some_cause_type = None
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)
    an_investigating_incident_state = an_incident_state(some_alert, IncidentStatus.INVESTIGATING)
    some_incident_id = an_investigating_incident_state.incident_id
    _investigation_returned = partial(_set_investigate_return_value, investigate)

    Scenario() \
        .given(
            lambda: _investigation_returned(some_hypothesis, some_low_confidence, some_cause_type)
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
                    "hypothesis": some_hypothesis, 
                    "confidence": some_low_confidence, 
                    "status": IncidentStatus.ESCALATED
                }
            ),
            assert_that(record_hypothesis).was_called_with(
                some_incident_id, some_hypothesis, some_low_confidence, some_cause_type
            ),
            assert_that(transition_incident).was_called_with(
                some_incident_id,
                IncidentStatus.ESCALATED,
                actor=Actor.INVESTIGATOR,
                action=matcher(is_not_none),
                result=some_hypothesis,
                confidence=some_low_confidence,
            ),
        ))


def _set_investigate_return_value(investigate: MagicMock, *values: object) -> None:
    investigate.return_value = values
