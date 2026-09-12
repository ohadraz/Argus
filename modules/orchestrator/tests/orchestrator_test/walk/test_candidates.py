from __future__ import annotations

import pytest
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.candidates import the_next_worth_trying

from ..framework.builders import (
    a_determined_hypothesis,
    a_random_id,
    an_undetermined_hypothesis,
)

"""Which explanation on the list is worth an experiment, asked directly.

The question two nodes share - the investigation choosing where to start, and
the walk choosing where to go after a refutation - so it is asked here once
rather than twice through its callers. What those callers do with the answer is
their own subject; this is only about which candidate comes back.

Two things disqualify one, and neither is confidence. A candidate that named no
cause has nothing to change on its account, and a candidate blaming a subject
this incident already changed and put back would be the same experiment run
twice. Everything else on the list is worth trying, however far down it sits.
"""

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_MOMENT = "2026-09-10T09:12:00+00:00"

type Chosen = tuple[int, Hypothesis] | None


@pytest.mark.unit
def test_the_first_candidate_worth_an_experiment_is_the_one_taken_up() -> None:
    some_incident_id = a_random_id()
    some_best_answer = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := [some_best_answer, a_determined_hypothesis(some_incident_id)]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_best_answer),
            _it_sits_at(0))
        )


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_passed_over() -> None:
    # "I found no cause" names nothing to change, which is a different answer
    # from being unsure which of several it is. Acting on it would mean changing
    # production with no hypothesis behind the change at all.
    some_incident_id = a_random_id()
    some_candidate_that_named_something = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := [an_undetermined_hypothesis(some_incident_id),
                                some_candidate_that_named_something]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_candidate_that_named_something),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_a_subject_already_tried_is_passed_over() -> None:
    # The same flag was changed earlier in this incident and the service did not
    # recover. Changing it again would be running the experiment that has
    # already been run, against a world that answered once.
    some_incident_id = a_random_id()
    some_candidate_blaming_something_else = _a_candidate_blaming(some_incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            some_candidates := [_a_candidate_blaming(some_incident_id, SOME_FLAG),
                                some_candidate_blaming_something_else]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, 
                                          [_an_attempt_on(SOME_FLAG)], 
                                          start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_candidate_blaming_something_else),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_an_attempt_on_something_nobody_proposed_disqualifies_nothing() -> None:
    # A later round is told everything this incident tried, and most of it will
    # have nothing to do with the explanations now on the list.
    some_incident_id = a_random_id()
    some_only_candidate = _a_candidate_blaming(some_incident_id, SOME_FLAG)

    Scenario() \
        .given(some_candidates := [some_only_candidate]) \
        .when(lambda: the_next_worth_trying(some_candidates, 
                                            [_an_attempt_on(ANOTHER_FLAG)], 
                                            start=0)
        ) \
        .then(_the_candidate_taken_up_is(some_only_candidate))


@pytest.mark.unit
def test_a_doubtful_candidate_is_worth_an_experiment_like_any_other() -> None:
    # The list is ordered by confidence, so a candidate this far down is only
    # ever reached once everything the model believed more has been refuted - by
    # which point the ranking has been proved wrong about the ones above it.
    some_incident_id = a_random_id()
    some_barely_believed = 0.05
    some_doubtful_candidate = a_determined_hypothesis(some_incident_id, 
                                                      confidence=some_barely_believed)

    Scenario() \
        .given(some_candidates := [some_doubtful_candidate]) \
        .when(lambda: the_next_worth_trying(some_candidates, [], start=0)) \
        .then(_the_candidate_taken_up_is(some_doubtful_candidate))


@pytest.mark.unit
def test_what_the_walk_has_already_passed_is_not_reconsidered() -> None:
    # `start` is where the walk has got to, not a hint. A candidate behind it
    # was either tried or passed over on its own merits, and reaching back for
    # it would put the walk in a loop over the same list.
    some_incident_id = a_random_id()
    dont_care_determined_candidate = a_determined_hypothesis(some_incident_id)
    some_determined_candidate_after_it = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := [dont_care_determined_candidate,
                                some_determined_candidate_after_it]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=1)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_determined_candidate_after_it),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_a_list_with_nothing_left_on_it_is_spent() -> None:
    # Which is what buys another investigation, or ends the walk. Distinct from
    # any candidate at all, so the caller can tell "nothing worth trying" from
    # "the first one".
    some_incident_id = a_random_id()

    Scenario() \
        .given(
            every_candidate_tried := [_a_candidate_blaming(some_incident_id, SOME_FLAG),
                                      an_undetermined_hypothesis(some_incident_id)]
        ) \
        .when(lambda: the_next_worth_trying(
            every_candidate_tried, [_an_attempt_on(SOME_FLAG)], start=0
        )) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_a_walk_past_the_end_of_the_list_is_spent() -> None:
    # The ordinary way the last candidate's refutation arrives here.
    some_incident_id = a_random_id()

    Scenario() \
        .given(some_candidates := [a_determined_hypothesis(some_incident_id)]) \
        .when(lambda: the_next_worth_trying(some_candidates, [], start=1)) \
        .then(_nothing_is_worth_trying())


def _a_candidate_blaming(incident_id: str, flag: str) -> Hypothesis:
    """An explanation that names the flag it blames.

    Built here rather than through the shared builder because the subject is
    what half of these cases turn on: what is refused twice is a *subject*, not
    a hypothesis object, and two candidates blaming the same flag are different
    findings about the same thing.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="kukibuki hypothesis",
                      cause_type=CauseType.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def _an_attempt_on(flag: str) -> Attempt:
    """A mitigation this incident already took on that flag, and undid again.

    Everything but the subject is arbitrary: only the subject is read here, and
    an attempt exists on the list at all only because it failed.
    """
    return Attempt(subject=flag, enabled=False, occurred_at=DONT_CARE_MOMENT)


def _the_candidate_taken_up_is(expected: Hypothesis) -> Assertion[Chosen]:
    def assertion(chosen: Chosen) -> bool:
        if chosen is None:
            raise AssertionError(
                f"expected the candidate {expected.summary!r} blaming "
                f"{expected.subject!r}, nothing was worth trying"
            )

        _, candidate = chosen

        if candidate != expected:
            raise AssertionError(
                f"expected the candidate blaming {expected.subject!r}, "
                f"got the one blaming {candidate.subject!r}"
            )

        return True

    return assertion


def _it_sits_at(expected: int) -> Assertion[Chosen]:
    """Where on the list the candidate came from.

    Asserted beside the candidate itself rather than instead of it: the index is
    what the walk carries forward, so a right answer returned with the wrong
    index sends the next round back over ground it has covered.
    """
    def assertion(chosen: Chosen) -> bool:
        if chosen is None:
            raise AssertionError(f"expected a candidate at {expected}, got none at all")

        index, _ = chosen

        if index != expected:
            raise AssertionError(f"expected the candidate at {expected}, got {index}")

        return True

    return assertion


def _nothing_is_worth_trying() -> Assertion[Chosen]:
    def assertion(chosen: Chosen) -> bool:
        if chosen is not None:
            _, candidate = chosen
            raise AssertionError(
                "expected a spent list, got the candidate blaming "
                f"{candidate.subject!r}"
            )

        return True

    return assertion
