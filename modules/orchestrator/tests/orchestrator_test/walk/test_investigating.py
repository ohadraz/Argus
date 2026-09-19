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

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.events import AgentInvoked, CandidatesReordered, IncidentEvent
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Actor,
    Alert,
    Attempt,
    Evidence,
    FailureMode,
    Hypothesis,
    IncidentStatus,
    Reading,
    RetrievalChannel,
    Verdict,
)
from argus_testkit import Assertion, Kept, Scenario, all_of, calling
from incident_memory.records import RememberedIncident, WhatWasTried
from orchestrator.walk import ports
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.investigating import investigator_node, route_after_investigation
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import assert_that, the_result_at, the_result_is
from orchestrator_test.framework.builders import (
    a_determined_hypothesis,
    an_incident_state,
    an_undetermined_hypothesis,
)

SOME_FLAG = "monthly-spend-feature"


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.Investigate, instance=True))


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
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=some_hypothesis,
                    candidates=[some_hypothesis],
                    candidate_index=0,
                    already_read=[],
                    rounds=1,
                    confidence=some_hypothesis.confidence,
                    nothing_worth_trying=False,
                    narration=Narration(action="hypothesis formed")
                )
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
                                      recall_similar=_nothing_like_it_has_happened(),
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
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=a_hypothesis_with_no_cause,
                    candidates=[a_hypothesis_with_no_cause],
                    candidate_index=0,
                    already_read=[],
                    rounds=1,
                    confidence=None,
                    nothing_worth_trying=True,
                    narration=Narration(action="insufficient evidence")
                )
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
                                      recall_similar=_nothing_like_it_has_happened(),
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
                                      recall_similar=_nothing_like_it_has_happened(),
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
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_an_investigation_that_named_none_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_investigation(an_escalated_incident)) \
        .then(_the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_a_subject_an_earlier_incident_refuted_is_tried_last(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The one thing memory is allowed to do to a walk. The model believed the
    # first candidate more, and an earlier incident says changing that subject
    # did not help - which is evidence the model had no way to weigh, because
    # it is not about this incident at all.
    an_investigating_incident = _an_investigating_incident()
    the_flag_that_failed_before = "monthly-spend-feature"
    the_flag_nobody_has_tried = "legacy-checkout-fallback"

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                _a_candidate_blaming(an_investigating_incident.incident_id,
                                     the_flag_that_failed_before),
                _a_candidate_blaming(an_investigating_incident.incident_id,
                                     the_flag_nobody_has_tried)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    the_flag_that_failed_before
                ),
                record_hypothesis=record_hypothesis)
        ) \
        .then(_the_candidates_are_about([the_flag_nobody_has_tried,
                                         the_flag_that_failed_before]))


@pytest.mark.unit
def test_an_order_memory_changed_is_said_on_the_timeline(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for.
    an_investigating_incident = _an_investigating_incident()
    the_flag_that_failed_before = "monthly-spend-feature"
    the_incident_that_moved_it = "3f2b1a09-0000-4000-8000-00000000000a"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                _a_candidate_blaming(an_investigating_incident.incident_id,
                                     the_flag_that_failed_before),
                _a_candidate_blaming(an_investigating_incident.incident_id,
                                     "legacy-checkout-fallback")
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    the_flag_that_failed_before,
                    incident_id=the_incident_that_moved_it
                ),
                record_hypothesis=record_hypothesis,
                publisher=published.take)
        ) \
        .then(_it_was_said_that(published,
                               the_flag_that_failed_before,
                               the_incident_that_moved_it))


@pytest.mark.unit
def test_an_order_memory_left_alone_is_not_said(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The ordinary incident, and the one that has to stay silent. A line on
    # every walk saying the order did not change is a timeline nobody reads.
    an_investigating_incident = _an_investigating_incident()
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                _a_candidate_blaming(an_investigating_incident.incident_id,
                                     "monthly-spend-feature")
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_nothing_like_it_has_happened(),
                record_hypothesis=record_hypothesis,
                publisher=published.take)
        ) \
        .then(_no_reordering_was_said(published))


def _an_earlier_incident_that_refuted(
    flag: str,
    incident_id: str = "3f2b1a09-0000-4000-8000-00000000000a"
) -> ports.RecallSimilar:
    """Memory holding one incident that changed this flag and did not recover.

    Everything a search would have needed to find it is arbitrary: the search
    already happened by the time a walk reads one, and what it reads is the
    list of what was tried.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return [
            RememberedIncident(
                incident_id=incident_id,
                described_as="an incident that looked like this one",
                service="kuki-service",
                alert_name="HighErrorRate",
                tried=[WhatWasTried(subject=flag, verdict=Verdict.REFUTED)]
            )
        ]

    return recall


def _the_candidates_are_about(expected: list[str]) -> Assertion[StateDelta]:
    def assertion(delta: StateDelta) -> bool:
        if delta.candidates is None:
            raise AssertionError(
                f"expected {expected}, the delta carried no candidates"
            )

        subjects = [candidate.subject for candidate in delta.candidates]

        if subjects != expected:
            raise AssertionError(f"expected {expected}, got {subjects}")

        return True

    return assertion


def _it_was_said_that(published: Kept[IncidentEvent],
                      subject: str,
                      on_the_strength_of: str) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, CandidatesReordered)
        ]

        if not said:
            raise AssertionError(
                f"expected a reordering to be said, got "
                f"{[event.kind for event in published.taken]}"
            )

        if said[0].subject != subject:
            raise AssertionError(
                f"expected [{subject}] to have moved, got [{said[0].subject}]"
            )

        if said[0].on_the_strength_of != on_the_strength_of:
            raise AssertionError(
                f"expected it said on [{on_the_strength_of}], "
                f"got [{said[0].on_the_strength_of}]"
            )

        return True

    return assertion


def _no_reordering_was_said(published: Kept[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, CandidatesReordered)
        ]

        if said:
            raise AssertionError(f"expected no reordering to be said, got {said}")

        return True

    return assertion


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
                                      recall_similar=_nothing_like_it_has_happened(),
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
                                      recall_similar=_nothing_like_it_has_happened(),
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
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def _an_attempt_on(subject: str) -> Attempt:
    return Attempt(action_type=REVERT_FEATURE_FLAG,
                   subject=subject,
                   enabled=False,
                   occurred_at="2026-08-29T16:00:00Z")


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


def _nothing_like_it_has_happened() -> ports.RecallSimilar:
    """Memory with nothing in it, which is what every case here assumes.

    These are cases about what an investigation found and what the walk does
    with it. What an earlier incident was done about is a different subject with
    a file of its own, and a recall answering here would put a second reason
    behind every order these cases assert.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return []

    return recall
