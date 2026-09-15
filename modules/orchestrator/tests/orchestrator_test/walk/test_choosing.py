"""Walking the candidates an investigation offered, one at a time.

Being wrong about a correlated change is the ordinary case in an incident, not
the exceptional one, so a refuted mitigation is not the end of what Argus can
do - it is the end of what Argus can do *about that candidate*. These cover the
decision made after each attempt: try the next explanation, buy a wider look,
or admit there are no moves left.

One node owns that decision. Both ways an attempt can fail to settle anything -
the gate refusing it, and the service refusing to recover - arrive at the same
place, because "what now" has one answer and splitting it across two nodes
would be two chances to get it wrong.

The node reports what it found and never a status. Where that leaves the
incident is derived from the state it produced, which is what `_the_walk_goes_to`
does here and what the graph does in production.

Nothing here tells anybody. A longer walk is a longer silence before a human
hears anything, and what closes that gap is the relay in `agent_communicator`,
which follows the events these decisions are published as - so the node
decides, publishes, and knows nothing about who is listening.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_core.events import CandidateSelected, IncidentEvent
from argus_core.models import (
    Alert,
    CauseType,
    Evidence,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    RevertFeatureFlag,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.choosing import next_candidate_node, route_after_next_candidate
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.routes import FIXING_ROUTE, INVESTIGATING_ROUTE, MITIGATING_ROUTE
from orchestrator.walk.state import IncidentState, status_after

from orchestrator_test.framework.builders import (
    a_determined_hypothesis,
    a_random_id,
    an_undetermined_hypothesis,
)

# How many times one incident may be investigated. Stated rather than read:
# the node is told its budget now, and a test taking the number from the
# same configuration would agree with itself whatever either said.
SOME_ROUND_BUDGET = 3

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")


@pytest.mark.unit
def test_a_refuted_candidate_hands_over_to_the_next_one() -> None:
    incident_id = a_random_id()
    the_next_candidate = a_determined_hypothesis(incident_id)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), the_next_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            _the_updates_carry("candidate_index", 1),
            _the_updates_carry("hypothesis", the_next_candidate),
            _the_walk_goes_to(MITIGATING_ROUTE, a_walk)))


@pytest.mark.unit
def test_moving_to_the_next_candidate_is_published_rather_than_narrated() -> None:
    # This node's own comment says it: narration, and no transition behind it.
    # Moving to the next candidate is progress through a phase rather than out
    # of one, so the only account of it has to be an event - and which
    # explanation is now under test is the thing the lines after this are about.
    incident_id = a_random_id()
    the_next_candidate = a_determined_hypothesis(incident_id)
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), the_next_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET,
                                          publisher=published.append)) \
        .then(all_of(
            _the_candidate_selected_was(the_next_candidate, published),
            _nothing_was_narrated()))


@pytest.mark.unit
def test_what_was_tried_is_remembered_for_the_round_after() -> None:
    # A later investigation is only worth running because it can be told this.
    # Recorded here rather than in the investigator node, so the fact stays
    # attached to the attempt that produced it.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 acted_on=SOME_FLAG)
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_attempts_recorded_are([SOME_FLAG]))


@pytest.mark.unit
def test_a_walk_with_a_candidate_left_carries_on() -> None:
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id),
                 a_determined_hypothesis(incident_id)],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(MITIGATING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_spent_list_buys_another_investigation() -> None:
    # Every explanation this round offered has been tried and failed, which is
    # the moment another round is worth paying for - and what pays for it is the
    # refutation rather than a wider window. Argus changed production and the
    # service did not answer; no amount of re-reading produces that fact, and
    # the model has never seen it. One round is already spent here, which is the
    # ordinary shape of a hard incident by the time its first answer comes back
    # refuted.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 rounds=1)
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(INVESTIGATING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_walk_that_has_used_every_round_ends() -> None:
    # The bound is a count of rounds rather than the walk's own judgement: each
    # round is a model call and another set of real changes to production, and
    # "keep going until something works" is not a stopping condition.
    #
    # It ends in `fixing`, not `escalated`: nothing reversible is left and what
    # remains is a permanent fix, which is what Code-Fix is for. `escalated`
    # comes later, once Code-Fix has nothing either.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 rounds=_every_round())
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(FIXING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_doubtful_candidate_is_tried_like_any_other() -> None:
    # Confidence orders the list; it does not decide who gets on it. By the time
    # the walk reaches a doubtful candidate, every explanation the model
    # believed more has been tried and refuted - so the ranking that made this
    # one doubtful has already been proved wrong about the ones above it, and
    # the cost of finding out is one reversible change and two minutes.
    some_doubtful_confidence = 0.4
    incident_id = a_random_id()
    a_doubtful_candidate = a_determined_hypothesis(incident_id, some_doubtful_confidence)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), a_doubtful_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(_the_walk_goes_to(MITIGATING_ROUTE, a_walk),
                     _the_updates_carry("hypothesis", a_doubtful_candidate)))


@pytest.mark.unit
def test_a_candidate_blaming_a_flag_already_tried_is_skipped() -> None:
    # The same subject, twice on one list. Changing it again would be running
    # the experiment that has already been run and undone, against a world that
    # answered once - so the walk passes over it and reaches the first
    # explanation that is actually new.
    incident_id = a_random_id()
    a_candidate_blaming_something_else = _a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [_a_candidate_blaming(incident_id, SOME_FLAG),
                 _a_candidate_blaming(incident_id, SOME_FLAG),
                 a_candidate_blaming_something_else],
                index=0,
                acted_on=SOME_FLAG
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            _the_updates_carry("hypothesis", a_candidate_blaming_something_else),
            _the_updates_carry("candidate_index", 2)))


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_never_tried() -> None:
    # The one thing on the list that is not an experiment. "I found no cause"
    # names nothing to change, which is a different answer from "I am unsure
    # which of these it is" - and acting on it would mean changing production
    # with no hypothesis behind the change at all.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id),
                 an_undetermined_hypothesis(incident_id)],
                index=0,
                rounds=_every_round()
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(_the_walk_goes_to(FIXING_ROUTE, a_walk),
                     _no_candidate_was_taken_up()))


def _every_round() -> int:
    return SOME_ROUND_BUDGET


def _a_walk_at(incident_id: str,
               candidates: list[Hypothesis],
               index: int,
               acted_on: str = SOME_FLAG,
               rounds: int = 1) -> IncidentState:
    """An incident mid-walk: a candidate has just been tried and did not settle
    anything, and the state carries what it takes to decide what happens next.

    Nothing is carried in `already_read` throughout this file. The walk is
    bounded by how many times the incident may be investigated, not by how much
    of the window is left unread - a hard incident has usually read everything
    it can reach by the time the answer it found gets refuted, and that is
    exactly when another round is worth buying.
    """
    return IncidentState(
        incident_id=incident_id,
        alert=DONT_CARE_ALERT,
        status=IncidentStatus.MITIGATING,
        candidates=candidates,
        candidate_index=index,
        hypothesis=candidates[index],
        rounds=rounds,
        proposed_action=RevertFeatureFlag(
            flag=acted_on,
            enabled=False,
            undo_descriptor=FlagUndo(flag=acted_on, was_enabled=True)
        )
    )


def _a_candidate_blaming(incident_id: str, flag: str) -> Hypothesis:
    """An explanation that names the flag it blames.

    Built here rather than through the shared builder because the subject is
    the whole point of these cases: what the walk refuses to try twice is a
    *subject*, not a hypothesis object, and two candidates blaming the same flag
    are different findings about the same thing.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="kukibuki hypothesis",
                      cause_type=CauseType.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def _the_walk_goes_to(expected: str, state: IncidentState) -> Assertion[StateDelta]:
    """Where the graph takes the state this node produced.

    The status is derived rather than read off the updates, because the node no
    longer supplies one - so this asserts where the node's work actually leaves
    the incident, by exactly the path the graph takes. `narration` is dropped on
    the way, as the graph drops it: it is what the node said, not part of the
    state.
    """
    def assertion(updates: StateDelta) -> bool:
        work = updates.as_updates()
        after = state.model_copy(update=work)
        routed = route_after_next_candidate(
            after.model_copy(update={"status": status_after(after, _every_round())})
        )

        if routed != expected:
            raise AssertionError(
                f"Expected the walk to go to [{expected}], it went to [{routed}]."
            )

        return True

    return assertion


def _the_updates_carry(field: str, expected: Any) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if field not in updates.model_fields_set:
            raise AssertionError(
                f"Expected the updates to carry [{field}], they carry "
                f"{sorted(updates.model_fields_set)}."
            )

        if getattr(updates, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], it was "
                f"[{getattr(updates, field)}]."
            )

        return True

    return assertion


def _no_candidate_was_taken_up() -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if "hypothesis" in updates.model_fields_set:
            raise AssertionError(
                f"Expected no candidate to be taken up, the node took up "
                f"[{updates.hypothesis}]."
            )

        return True

    return assertion


def _the_attempts_recorded_are(expected: list[str]) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        recorded = [attempt.subject for attempt in updates.attempts or []]
        if recorded != expected:
            raise AssertionError(
                f"Expected the attempts to record {expected}, they record {recorded}."
            )

        return True

    return assertion


def _the_candidate_selected_was(expected: Hypothesis,
                                published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The explanation the next few lines are about, said out loud.

    Published rather than left to be inferred from the ranked list: the walk
    skips any candidate it cannot act on, so a reader given only the ranking
    cannot tell which one an attempt belongs to.
    """
    def assertion(dont_care_updates: StateDelta) -> bool:
        selected = [event for event in published if isinstance(event, CandidateSelected)]

        if not selected:
            raise AssertionError(
                f"Expected the candidate now under test to be published, got "
                f"{[event.kind for event in published]}."
            )

        if selected[0].hypothesis_id != expected.id:
            raise AssertionError(
                f"Expected [{expected.id}] published, got "
                f"[{selected[0].hypothesis_id}]."
            )

        return True

    return assertion


def _nothing_was_narrated() -> Assertion[StateDelta]:
    """Moving on to the next candidate moves the incident nowhere.

    It was mitigating before and is mitigating after, so there is no transition
    for a narration to account for - and a sentence returned anyway is what
    routed this into a second account of an event already published.
    """
    def assertion(updates: StateDelta) -> bool:
        if updates.narration is not None:
            raise AssertionError(
                f"Expected no narration where the incident moved nowhere, it "
                f"said [{updates.narration.action}]."
            )

        return True

    return assertion
