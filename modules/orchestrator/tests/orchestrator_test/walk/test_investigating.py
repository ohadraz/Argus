"""What one round of investigation leaves behind, which is its work and its
account of it - never a status.

Where the incident stands is derived from these returns one place further out,
by `status_after`, and tested there. A node asserting a status here would be
asserting a decision it no longer makes.

A cause was named is the whole admission test. Confidence used to gate it, and
that was the wrong question: the action is taken alone, confirmed against the
service and put back when it does not help, so an unsure answer is a reason to
try it and see.

The round also reads the flag provider, which the proposal node used to do. It
has to: what memory compares, and what the walk skips, is the action a
candidate would be answered with - and that question cannot be asked before the
history is in hand. So the cases about reading it are here, beside the ones
about what is done with what it said.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.events import (
    AgentInvoked,
    CandidatesReordered,
    FlagChangesRetrieved,
    IncidentEvent,
)
from argus_core.models import (
    ActionIdentity,
    Actor,
    Alert,
    Attempt,
    FlagChange,
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

from orchestrator_test.framework.assertions import (
    assert_that,
    the_result_at,
    the_result_is,
    the_route_is,
)
from orchestrator_test.framework.builders import (
    a_candidate_blaming,
    a_determined_hypothesis,
    a_leak_blamed_on,
    an_identity,
    an_incident_state,
    an_undetermined_hypothesis,
    putting_back,
    restarting,
)

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
SOME_SERVICE = "kuki-service"
DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"

# Every flag these cases name, recorded as having moved. Fixed rather than
# varied per case: a candidate blaming a flag the provider never recorded is
# answered by no action at all, and a case about the order of two candidates
# would quietly become a case about neither of them being answerable.
WHAT_THE_PROVIDER_RECORDED = [
    FlagChange(flag=SOME_FLAG, enabled=True, occurred_at=DONT_CARE_MOMENT),
    FlagChange(flag=ANOTHER_FLAG, enabled=True, occurred_at=DONT_CARE_MOMENT)
]


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.Investigate, instance=True))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordHypothesis, instance=True))


@pytest.fixture
def fetch_flag_changes() -> MagicMock:
    fetch = cast(MagicMock, create_autospec(ports.FetchFlagChanges, instance=True))
    fetch.return_value = list(WHAT_THE_PROVIDER_RECORDED)

    return fetch


@pytest.mark.unit
def test_investigator_node_offers_the_cause_it_named_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=some_hypothesis,
                    candidates=[some_hypothesis],
                    candidate_index=0,
                    flag_changes=WHAT_THE_PROVIDER_RECORDED,
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
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(
            the_result_at("hypothesis", a_doubtful_hypothesis),
            the_result_at("nothing_worth_trying", False)
        ))


@pytest.mark.unit
def test_investigator_node_reports_a_round_that_named_no_cause_at_all(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=a_hypothesis_with_no_cause,
                    candidates=[a_hypothesis_with_no_cause],
                    candidate_index=0,
                    flag_changes=WHAT_THE_PROVIDER_RECORDED,
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
        .then(the_route_is(MITIGATING_ROUTE))


@pytest.mark.unit
def test_every_candidate_the_investigation_offered_is_recorded(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(
            _every_candidate_was_recorded([the_best_answer, a_runner_up],
                                          record_hypothesis),
            the_result_at("candidates", [the_best_answer, a_runner_up]),
            the_result_at("candidate_index", 0),
            the_result_at("hypothesis", the_best_answer)))


@pytest.mark.unit
def test_a_resumed_investigation_is_told_what_was_read_and_what_failed(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # Both halves of what makes a second round worth paying for. Without what
    # was already read it cannot tell a fresh window from one it has seen;
    # without the attempts it re-answers the question that has already been
    # answered.
    a_window_already_read = Reading(channel=RetrievalChannel.LOGS,
                                    window_start="2026-08-20T10:30:00Z",
                                    window_end="2026-08-20T11:08:00Z")
    a_refuted_attempt = _an_attempt_to(putting_back(SOME_FLAG))
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(all_of(
            _the_investigation_was_told("already_read", [a_window_already_read],
                                        investigate),
            _the_investigation_was_told("already_refuted", [a_refuted_attempt],
                                        investigate)))


@pytest.mark.unit
def test_a_later_round_does_not_act_on_an_explanation_already_refuted(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
        update={"attempts": [_an_attempt_to(putting_back(SOME_FLAG))]}
    )
    the_same_explanation_again = a_candidate_blaming(
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
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_a_later_round_does_not_restart_a_service_it_already_restarted(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # The same guard, for the kind of action it never used to cover. A leak is
    # described in fresh prose every round, so comparing the candidates found
    # nothing alike and the walk would restart one service once per candidate -
    # with the gate's cap as the only thing stopping it.
    a_round_after_the_restart = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_to(restarting(SOME_SERVICE))]}
    )
    the_same_leak_in_other_words = a_leak_blamed_on(
        a_round_after_the_restart.incident_id, "unbounded cache growth"
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_same_leak_in_other_words))
        ) \
        .when(
            lambda: investigator_node(a_round_after_the_restart,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_an_investigation_that_named_none_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_investigation(an_escalated_incident)) \
        .then(the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_an_action_an_earlier_incident_refuted_is_tried_last(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # The one thing memory is allowed to do to a walk. The model believed the
    # first candidate more, and an earlier incident says taking that action did
    # not help - which is evidence the model had no way to weigh, because it is
    # not about this incident at all.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    putting_back(SOME_FLAG)
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(_the_candidates_are_about([ANOTHER_FLAG, SOME_FLAG]))


@pytest.mark.unit
def test_a_restart_an_earlier_incident_refuted_demotes_a_leak_worded_otherwise(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # What the identity bought across incidents. Two incidents describe one
    # leak in two sets of words, and a restart addressed to the alert's service
    # is the same experiment in both - which the record could not say while it
    # kept the model's prose as the thing it was found by.
    an_investigating_incident = _an_investigating_incident()
    the_leak_nobody_worded_the_same_way = "kuki-service resident set climbing"

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_leak_blamed_on(an_investigating_incident.incident_id,
                                  the_leak_nobody_worded_the_same_way),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    restarting(SOME_SERVICE)
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes)
        ) \
        .then(_the_candidates_are_about([ANOTHER_FLAG,
                                         the_leak_nobody_worded_the_same_way]))


@pytest.mark.unit
def test_an_order_memory_changed_is_said_on_the_timeline(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for. What
    # is said is the action, because "moved kuki-service down the list" is true
    # of a service restarted and of a flag put back.
    an_investigating_incident = _an_investigating_incident()
    the_incident_that_moved_it = "3f2b1a09-0000-4000-8000-00000000000a"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    putting_back(SOME_FLAG), incident_id=the_incident_that_moved_it
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                publisher=published.take)
        ) \
        .then(_it_was_said_that(published,
                                putting_back(SOME_FLAG),
                                the_incident_that_moved_it))


@pytest.mark.unit
def test_an_order_memory_left_alone_is_not_said(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # The ordinary incident, and the one that has to stay silent. A line on
    # every walk saying the order did not change is a timeline nobody reads.
    an_investigating_incident = _an_investigating_incident()
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_nothing_like_it_has_happened(),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                publisher=published.take)
        ) \
        .then(_no_reordering_was_said(published))


@pytest.mark.unit
def test_the_round_says_what_flag_history_it_reasoned_from(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # Every action this round might propose rests on this and nothing else:
    # which flag moved, which way, and when. Published from the node that reads
    # it, because by the time an action exists the history has already been
    # reduced to one decision about one flag.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      publisher=published.take)
        ) \
        .then(_the_history_published_is(WHAT_THE_PROVIDER_RECORDED, published))


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_not_published_as_an_empty_one(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
) -> None:
    # "Nothing changed" and "the provider did not answer" lead to the same
    # place - no action - and are not the same fact. A page showing an empty
    # history for the second would be stating that nothing had changed, and a
    # round carrying one forward would let the proposal node act on it.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      publisher=published.take)
        ) \
        .then(all_of(
            _no_history_was_published(published),
            the_result_at("flag_changes", None)))


@pytest.mark.unit
def test_the_graph_says_when_it_invokes_the_investigator(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      fetch_flag_changes=fetch_flag_changes,
                                      publisher=published.append)
        ) \
        .then(_the_agents_invoked_were([Actor.INVESTIGATOR], published))


@pytest.mark.unit
def test_the_investigation_publishes_to_the_same_place_the_graph_does(
    investigate: MagicMock, record_hypothesis: MagicMock, fetch_flag_changes: MagicMock
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
                                      fetch_flag_changes=fetch_flag_changes,
                                      publisher=published.append)
        ) \
        .then(_the_investigation_was_told("publisher", published.append, investigate))


def _the_provider_cannot_be_reached(fetch_flag_changes: MagicMock) -> None:
    fetch_flag_changes.side_effect = RuntimeError(
        "The Feature Flag provider could not be reached."
    )


def _an_earlier_incident_that_refuted(
    identity: ActionIdentity,
    incident_id: str = "3f2b1a09-0000-4000-8000-00000000000a"
) -> ports.RecallSimilar:
    """Memory holding one incident that took this action and did not recover.

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
                service=SOME_SERVICE,
                alert_name="HighErrorRate",
                tried=[WhatWasTried(identity=identity, verdict=Verdict.REFUTED)]
            )
        ]

    return recall


def _the_candidates_are_about(expected: list[str]) -> Assertion[StateDelta]:
    def assertion(delta: StateDelta) -> bool:
        if delta.candidates is None:
            raise AssertionError(
                f"Expected {expected}, the delta carried no candidates."
            )

        subjects = [candidate.subject for candidate in delta.candidates]

        if subjects != expected:
            raise AssertionError(f"Expected {expected}, got {subjects}")

        return True

    return assertion


def _it_was_said_that(published: Kept[IncidentEvent],
                      moved: ActionIdentity,
                      on_the_strength_of: str) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, CandidatesReordered)
        ]

        if not said:
            raise AssertionError(
                f"Expected a reordering to be said, got "
                f"{[event.kind for event in published.taken]}"
            )

        what_it_said = an_identity(said[0].action_type, said[0].subject)

        if what_it_said != moved:
            raise AssertionError(
                f"Expected [{moved}] to have moved, got [{what_it_said}]."
            )

        if said[0].on_the_strength_of != on_the_strength_of:
            raise AssertionError(
                f"Expected it said on [{on_the_strength_of}], "
                f"got [{said[0].on_the_strength_of}]."
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
            raise AssertionError(f"Expected no reordering to be said, got {said}")

        return True

    return assertion


def _the_history_published_is(expected: list[FlagChange],
                              published: Kept[IncidentEvent]
                              ) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        read = [event for event in published.taken
                if isinstance(event, FlagChangesRetrieved)]

        if len(read) != 1:
            raise AssertionError(f"Expected one FlagChangesRetrieved, got {len(read)}")

        if read[0].changes != expected:
            raise AssertionError(
                f"Expected the history {expected} to be published, got "
                f"{read[0].changes}"
            )

        return True

    return assertion


def _no_history_was_published(published: Kept[IncidentEvent]
                              ) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        read = [event for event in published.taken
                if isinstance(event, FlagChangesRetrieved)]

        if read:
            raise AssertionError(
                f"Expected an unreadable provider to publish no history, it "
                f"published {read}"
            )

        return True

    return assertion


def _an_investigating_incident() -> IncidentState:
    return _an_incident_in(IncidentStatus.INVESTIGATING)


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    some_alert = Alert(service=SOME_SERVICE, alert_name="HighErrorRate")

    return an_incident_state(some_alert, status)


def _the_investigation_returned(investigate: MagicMock,
                                *candidates: Hypothesis) -> None:
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[]
    )


def _an_attempt_to(identity: ActionIdentity) -> Attempt:
    return Attempt(identity=identity, enabled=False, occurred_at="2026-08-29T16:00:00Z")


def _every_candidate_was_recorded(expected: list[Hypothesis],
                                  record_hypothesis: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded = [call.args[0] for call in record_hypothesis.call_args_list]
        if recorded != expected:
            raise AssertionError(
                f"Expected {len(expected)} candidate(s) recorded, got {len(recorded)}"
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
                f"Expected the investigation to be told [{field}] = {expected}, "
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
                f"Expected {expected} to have been announced, got {invoked}"
            )

        return True

    return assertion


def _nothing_like_it_has_happened() -> ports.RecallSimilar:
    """Memory with nothing in it, which is what most cases here assume.

    These are cases about what an investigation found and what the walk does
    with it. What an earlier incident was done about is a different subject with
    a file of its own, and a recall answering here would put a second reason
    behind every order these cases assert.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return []

    return recall
