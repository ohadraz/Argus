from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.events import AgentInvoked, IncidentEvent, RetrievalChannel
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.reading import Reading
from argus_testkit import Assertion, Scenario, all_of, calling
from orchestrator.walk import ports
from orchestrator.walk.investigating import investigator_node, route_after_investigation
from orchestrator.walk.narrating import Narration
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE

from ..framework.assertions import assert_that, the_result_at, the_result_is
from ..framework.builders import (
    a_determined_hypothesis,
    an_incident_state,
    an_undetermined_hypothesis,
)

"""What one round of investigation leaves behind, which is its work and its
account of it - never a status.

Where the incident stands is derived from these returns one place further out,
by `status_after`, and tested there. A node asserting a status here would be
asserting a decision it no longer makes.

A cause was named is the whole admission test. Confidence used to gate it, and
that was the wrong question: the action is taken alone, confirmed against the
service and put back when it does not help, so an unsure answer is a reason to
try it and see.
"""

SOME_FLAG = "monthly-spend-feature"


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_investigator.investigate))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordHypothesis, instance=True))


@pytest.mark.unit
def test_investigator_node_offers_the_cause_it_named_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    an_investigating_incident = _an_investigating_incident()
    some_hypothesis = a_determined_hypothesis(an_investigating_incident.incident_id)

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate, some_hypothesis))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            the_result_is(
                {
                    "hypothesis": some_hypothesis,
                    "candidates": [some_hypothesis],
                    "candidate_index": 0,
                    "already_read": [],
                    "rounds": 1,
                    "confidence": some_hypothesis.confidence,
                    "nothing_worth_trying": False,
                    "narration": Narration(
                        action="hypothesis formed",
                        result=some_hypothesis.summary,
                        confidence=some_hypothesis.confidence
                    )
                }
            ),
            assert_that(record_hypothesis).was_called_with(some_hypothesis)
        ))


@pytest.mark.unit
def test_a_doubtful_cause_is_still_offered_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A cause was named, and that is the whole admission test for a reversible
    # mitigation. The ambiguous incident, where the model splits its confidence
    # across two explanations, is exactly the one this used to abandon and the
    # walk exists to work through.
    an_investigating_incident = _an_investigating_incident()
    some_doubtful_confidence = 0.4
    a_doubtful_hypothesis = a_determined_hypothesis(
        an_investigating_incident.incident_id, some_doubtful_confidence
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        a_doubtful_hypothesis))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            the_result_at("hypothesis", a_doubtful_hypothesis),
            the_result_at("nothing_worth_trying", False)
        ))


@pytest.mark.unit
def test_investigator_node_reports_a_round_that_named_no_cause_at_all(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The loop reached the end of what it could read and named nothing. The
    # timeline has to say *that*, not "hypothesis formed" - a human picking
    # the incident up needs to know whether to look for more evidence or to
    # doubt the one on file.
    #
    # `nothing_worth_trying` is the fact that carries it: it is what tells this
    # round apart from a walk that has worked through everything it was offered,
    # since the two leave the same candidate list behind.
    an_investigating_incident = _an_investigating_incident()
    a_hypothesis_with_no_cause = an_undetermined_hypothesis(
        an_investigating_incident.incident_id
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        a_hypothesis_with_no_cause))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            the_result_is(
                {
                    "hypothesis": a_hypothesis_with_no_cause,
                    "candidates": [a_hypothesis_with_no_cause],
                    "candidate_index": 0,
                    "already_read": [],
                    "rounds": 1,
                    "confidence": None,
                    "nothing_worth_trying": True,
                    "narration": Narration(
                        action="insufficient evidence",
                        result=a_hypothesis_with_no_cause.summary,
                        confidence=None
                    )
                }
            ),
            assert_that(record_hypothesis).was_called_with(a_hypothesis_with_no_cause)
        ))


@pytest.mark.unit
def test_an_investigation_that_named_a_cause_is_routed_to_the_proposal() -> None:
    Scenario() \
        .given(a_mitigating_incident := _an_incident_in(IncidentStatus.MITIGATING)) \
        .when(lambda: route_after_investigation(a_mitigating_incident)) \
        .then(_the_route_is(MITIGATING_ROUTE))


@pytest.mark.unit
def test_every_candidate_the_investigation_offered_is_recorded(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The incident's record should say what was considered, not only what was
    # acted on. A runner-up that never reached the table is a finding a human
    # picking the incident up cannot see Argus ever having had.
    an_investigating_incident = _an_investigating_incident()
    incident_id = an_investigating_incident.incident_id
    some_doubtful_confidence = 0.4
    the_best_answer = a_determined_hypothesis(incident_id)
    a_runner_up = a_determined_hypothesis(incident_id, some_doubtful_confidence)

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_best_answer,
                                                        a_runner_up))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            _every_candidate_was_recorded([the_best_answer, a_runner_up],
                                          record_hypothesis),
            the_result_at("candidates", [the_best_answer, a_runner_up]),
            the_result_at("candidate_index", 0),
            the_result_at("hypothesis", the_best_answer)))


@pytest.mark.unit
def test_a_resumed_investigation_is_told_what_was_read_and_what_failed(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # Both halves of what makes a second round worth paying for. Without what
    # was already read it cannot tell a fresh window from one it has seen;
    # without the attempts it re-answers the question that has already been
    # answered.
    a_window_already_read = Reading(channel=RetrievalChannel.LOGS,
                                    window_start="2026-08-20T10:30:00Z",
                                    window_end="2026-08-20T11:08:00Z")
    a_refuted_attempt = _an_attempt_on(SOME_FLAG)
    a_second_round = _an_investigating_incident().model_copy(
        update={"already_read": [a_window_already_read],
                "attempts": [a_refuted_attempt]}
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(a_second_round.incident_id)))
        ) \
        .when(
            lambda: investigator_node(a_second_round,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            _the_investigation_was_told("already_read", [a_window_already_read],
                                        investigate),
            _the_investigation_was_told("already_refuted", [a_refuted_attempt],
                                        investigate)))


@pytest.mark.unit
def test_a_later_round_does_not_act_on_an_explanation_already_refuted(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A second investigation is told what was tried, and is free to conclude the
    # same thing anyway - being told does not oblige it to change its mind. What
    # it must not do is send the walk back to change the same flag a second
    # time, which would spend the round budget flipping one flag back and forth.
    #
    # The round reports that it found nothing worth trying, which is what ends
    # the incident. It is a fact about the investigation, not a status: the walk
    # leaves an identical candidate list behind when it runs out, and those two
    # do not end the same way.
    a_round_after_that_flag_was_tried = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_on(SOME_FLAG)]}
    )
    the_same_explanation_again = _a_candidate_blaming(
        a_round_after_that_flag_was_tried.incident_id, SOME_FLAG
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_same_explanation_again))
        ) \
        .when(
            lambda: investigator_node(a_round_after_that_flag_was_tried,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_an_investigation_that_named_none_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_investigation(an_escalated_incident)) \
        .then(_the_route_is(ESCALATED_ROUTE))


def _an_investigating_incident() -> IncidentState:
    return _an_incident_in(IncidentStatus.INVESTIGATING)


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    return an_incident_state(some_alert, status)


def _the_investigation_returned(investigate: MagicMock,
                                *candidates: Hypothesis) -> None:
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[]
    )


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"expected the route [{expected}], got [{route}]")

        return True

    return assertion


@pytest.mark.unit
def test_the_graph_says_when_it_invokes_the_investigator(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A narration that begins at the first retrieval starts mid-sentence: the
    # Orchestrator handing the incident over is the thing that caused it.
    published: list[IncidentEvent] = []
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis,
                                      publisher=published.append)
        ) \
        .then(_the_agents_invoked_were([Actor.INVESTIGATOR], published))


@pytest.mark.unit
def test_the_investigation_publishes_to_the_same_place_the_graph_does(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The Investigator's own account and the graph's are one narration, and
    # they are only one if the node hands its publisher down rather than
    # letting the agent publish somewhere of its own.
    published: list[IncidentEvent] = []
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      record_hypothesis=record_hypothesis,
                                      publisher=published.append)
        ) \
        .then(_the_investigation_was_told("publisher", published.append, investigate))


def _a_candidate_blaming(incident_id: str, flag: str) -> Hypothesis:
    """An explanation that names the flag it blames.

    Built here rather than through the shared builder because the subject is
    the whole point of this case: what the walk refuses to try twice is a
    *subject*, not a hypothesis object.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="kukibuki hypothesis",
                      cause_type=CauseType.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=["some log line"],
                      subject=flag)


def _an_attempt_on(subject: str) -> Attempt:
    return Attempt(subject=subject, enabled=False, occurred_at="2026-08-29T16:00:00Z")


def _every_candidate_was_recorded(expected: list[Hypothesis],
                                  record_hypothesis: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded = [call.args[0] for call in record_hypothesis.call_args_list]
        if recorded != expected:
            raise AssertionError(
                f"expected {len(expected)} candidate(s) recorded, got {len(recorded)}"
            )

        return True

    return assertion


def _the_investigation_was_told(field: str,
                                expected: object,
                                investigate: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        told = investigate.call_args.kwargs[field]
        if told != expected:
            raise AssertionError(
                f"expected the investigation to be told [{field}] = {expected}, "
                f"it was told {told}"
            )

        return True

    return assertion


def _the_agents_invoked_were(expected: list[Actor],
                             published: list[IncidentEvent]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        invoked = [event.agent for event in published
                   if isinstance(event, AgentInvoked)]
        if invoked != expected:
            raise AssertionError(
                f"expected {expected} to have been announced, got {invoked}"
            )

        return True

    return assertion
