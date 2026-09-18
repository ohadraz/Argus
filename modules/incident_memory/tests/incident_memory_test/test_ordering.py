"""Where a past incident's refutations move this one's candidates.

The only thing memory is allowed to do to a walk. A subject that was changed on
a similar incident and did not help goes to the back of the list; everything
else keeps the order confidence gave it.

Demoted, never removed - which is the line these cases are mostly about. A past
incident is evidence about a past incident, the same flag can break the service
twice, and a walk that refused to try the only candidate it had on the strength
of a different incident's result would end in an escalation it had the means to
avoid.
"""

from __future__ import annotations

from typing import cast

import pytest
from argus_core.models import Verdict
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.ordering import Reordering, demoting_what_was_refuted
from incident_memory.records import RememberedIncident

from incident_memory_test.framework.builders import a_hypothesis, a_remembered_incident


@pytest.mark.unit
def test_a_subject_refuted_before_is_tried_after_one_that_was_not() -> None:
    # The whole point. The model believed this one more, and a past incident
    # says changing it did not help - which is evidence the model had no way to
    # weigh, because it is not about this incident at all.
    the_flag_that_failed_before = "new-checkout-flow"
    the_flag_nobody_has_tried = "payments-fallback"

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(
                    tried=[(the_flag_that_failed_before, Verdict.REFUTED)]
                )
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=the_flag_that_failed_before, confidence=0.9),
                a_hypothesis(subject=the_flag_nobody_has_tried, confidence=0.4)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([the_flag_nobody_has_tried, the_flag_that_failed_before]))


@pytest.mark.unit
def test_a_subject_confirmed_before_keeps_its_place() -> None:
    # A record says two things and only one of them demotes. That changing a
    # flag once fixed an incident is no reason at all to try it later.
    the_flag_that_worked_before = "new-checkout-flow"
    the_flag_nobody_has_tried = "payments-fallback"

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(
                    tried=[(the_flag_that_worked_before, Verdict.CONFIRMED)]
                )
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=the_flag_that_worked_before, confidence=0.9),
                a_hypothesis(subject=the_flag_nobody_has_tried, confidence=0.4)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([the_flag_that_worked_before, the_flag_nobody_has_tried]))


@pytest.mark.unit
def test_candidates_memory_says_nothing_about_keep_confidence_order() -> None:
    # The ordinary case, and the one that has to be exactly what it would have
    # been with no memory at all - otherwise "with memory" and "without" differ
    # in more than the one thing the benchmark is comparing.
    a_flag = "new-checkout-flow"
    another_flag = "payments-fallback"
    a_third_flag = "search-rerank"

    Scenario() \
        .given(nothing_like_this_has_happened := [a_remembered_incident(tried=[])]) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=a_flag, confidence=0.9),
                a_hypothesis(subject=another_flag, confidence=0.6),
                a_hypothesis(subject=a_third_flag, confidence=0.4)
            ],
            nothing_like_this_has_happened
        )) \
        .then(_the_order_is([a_flag, another_flag, a_third_flag]))


@pytest.mark.unit
def test_nothing_remembered_at_all_changes_nothing() -> None:
    # A cold store, a corpus with no match above the floor, and a store that
    # could not be reached all arrive here as the same empty list - and all
    # three have to leave the walk exactly as they found it.
    a_flag = "new-checkout-flow"
    another_flag = "payments-fallback"

    Scenario() \
        .given(nothing_was_recalled := cast(list[RememberedIncident], [])) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=a_flag, confidence=0.9),
                a_hypothesis(subject=another_flag, confidence=0.4)
            ],
            nothing_was_recalled
        )) \
        .then(all_of(
            _the_order_is([a_flag, another_flag]),
            _nothing_was_reordered()
        ))


@pytest.mark.unit
def test_every_candidate_refuted_before_leaves_the_order_as_it_was() -> None:
    # Demotion is relative, so demoting everything demotes nothing - and the
    # walk still tries them all. The alternative is an escalation Argus had the
    # means to avoid, on the strength of incidents that are not this one.
    a_flag = "new-checkout-flow"
    another_flag = "payments-fallback"

    Scenario() \
        .given(
            both_failed_before := [
                a_remembered_incident(tried=[(a_flag, Verdict.REFUTED),
                                             (another_flag, Verdict.REFUTED)])
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=a_flag, confidence=0.9),
                a_hypothesis(subject=another_flag, confidence=0.4)
            ],
            both_failed_before
        )) \
        .then(all_of(
            _the_order_is([a_flag, another_flag]),
            _nothing_was_reordered()
        ))


@pytest.mark.unit
def test_a_reordering_names_the_incident_it_was_made_on_the_strength_of() -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for.
    the_incident_that_settled_it = "the-one-last-month"
    the_flag_that_failed_before = "new-checkout-flow"

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(
                    incident_id=the_incident_that_settled_it,
                    tried=[(the_flag_that_failed_before, Verdict.REFUTED)]
                )
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=the_flag_that_failed_before, confidence=0.9),
                a_hypothesis(subject="payments-fallback", confidence=0.4)
            ],
            what_happened_before
        )) \
        .then(_it_was_reordered_on(the_incident_that_settled_it))


@pytest.mark.unit
def test_a_candidate_naming_no_subject_is_left_where_it_is() -> None:
    # An explanation that named a cause but nothing to change on its account.
    # Memory has nothing to match it against, and moving it would be moving it
    # for no reason anybody could read back.
    the_flag_that_failed_before = "new-checkout-flow"

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(
                    tried=[(the_flag_that_failed_before, Verdict.REFUTED)]
                )
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                a_hypothesis(subject=None, confidence=0.9),
                a_hypothesis(subject=the_flag_that_failed_before, confidence=0.6)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([None, the_flag_that_failed_before]))


def _the_order_is(expected: list[str | None]) -> Assertion[Reordering]:
    def assertion(reordered: Reordering) -> bool:
        subjects = [candidate.subject for candidate in reordered.candidates]

        if subjects != expected:
            raise AssertionError(f"expected {expected}, got {subjects}")

        return True

    return assertion


def _nothing_was_reordered() -> Assertion[Reordering]:
    def assertion(reordered: Reordering) -> bool:
        if reordered.on_the_strength_of is not None:
            raise AssertionError(
                f"expected nothing reordered, got [{reordered.on_the_strength_of}]"
            )

        return True

    return assertion


def _it_was_reordered_on(incident_id: str) -> Assertion[Reordering]:
    def assertion(reordered: Reordering) -> bool:
        if reordered.on_the_strength_of != incident_id:
            raise AssertionError(
                f"expected [{incident_id}], got [{reordered.on_the_strength_of}]"
            )

        return True

    return assertion
