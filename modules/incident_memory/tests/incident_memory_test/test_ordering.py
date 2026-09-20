"""Where a past incident's refutations move this one's candidates.

The only thing memory is allowed to do to a walk. An action that was taken on a
similar incident and did not help sends the candidate that would take it again
to the back of the list; everything else keeps the order confidence gave it.

The action, not the candidate. What a model calls a cause is prose, and no two
incidents write the same prose - so every case here builds its candidates with
one indistinguishable summary and tells them apart only by what each would be
answered with. A comparison that had quietly fallen back to the candidate's own
words would order them by nothing at all and fail.

Demoted, never removed - which is the line these cases are mostly about. A past
incident is evidence about a past incident, the same flag can break the service
twice, and a walk that refused to try the only candidate it had on the strength
of a different incident's result would end in an escalation it had the means to
avoid.
"""

from __future__ import annotations

from typing import cast

import pytest
from argus_core.models import (
    RESTART_SERVICE,
    ActionIdentity,
    Verdict,
    WhatWouldBeTried,
)
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.ordering import Reordering, demoting_what_was_refuted
from incident_memory.records import RememberedIncident

from incident_memory_test.framework.builders import (
    DONT_CARE_SUBJECT,
    a_hypothesis,
    a_remembered_incident,
    an_identity,
)


@pytest.mark.unit
def test_an_action_refuted_before_is_tried_after_one_that_was_not() -> None:
    # The whole point. The model believed this one more, and a past incident
    # says taking that action did not help - which is evidence the model had no
    # way to weigh, because it is not about this incident at all.
    the_flag_that_failed_before = an_identity("new-checkout-flow")
    the_flag_nobody_has_tried = an_identity("payments-fallback")

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
                _a_candidate_answered_by(the_flag_that_failed_before, 0.9),
                _a_candidate_answered_by(the_flag_nobody_has_tried, 0.4)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([the_flag_nobody_has_tried, the_flag_that_failed_before]))


@pytest.mark.unit
def test_a_restart_refuted_before_demotes_a_candidate_worded_nothing_like_it() -> None:
    # The case the subject alone could never answer. Two incidents describe a
    # leak in two different sets of words, and a restart addressed to the same
    # service is the same experiment in both - which is only visible once what
    # is compared is the action rather than the model's prose about the symptom.
    restarting_the_shop = an_identity("io-shop", RESTART_SERVICE)
    a_flag_nobody_has_tried = an_identity("payments-fallback")

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(tried=[(restarting_the_shop, Verdict.REFUTED)])
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                _a_candidate_answered_by(restarting_the_shop, 0.9),
                _a_candidate_answered_by(a_flag_nobody_has_tried, 0.4)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([a_flag_nobody_has_tried, restarting_the_shop]))


@pytest.mark.unit
def test_the_same_subject_done_a_different_way_keeps_its_place() -> None:
    # Both halves of the identity, or the key answers a question nobody asked.
    # A service restarted and a flag of the same name put back are different
    # experiments, and a record of one is no evidence at all about the other.
    restarting_the_shop = an_identity("io-shop", RESTART_SERVICE)
    putting_the_flag_back = an_identity("io-shop")
    a_flag_nobody_has_tried = an_identity("payments-fallback")

    Scenario() \
        .given(
            what_happened_before := [
                a_remembered_incident(tried=[(restarting_the_shop, Verdict.REFUTED)])
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                _a_candidate_answered_by(putting_the_flag_back, 0.9),
                _a_candidate_answered_by(a_flag_nobody_has_tried, 0.4)
            ],
            what_happened_before
        )) \
        .then(all_of(
            _the_order_is([putting_the_flag_back, a_flag_nobody_has_tried]),
            _nothing_was_reordered()
        ))


@pytest.mark.unit
def test_an_action_confirmed_before_keeps_its_place() -> None:
    # A record says two things and only one of them demotes. That taking an
    # action once fixed an incident is no reason at all to try it later.
    the_flag_that_worked_before = an_identity("new-checkout-flow")
    the_flag_nobody_has_tried = an_identity("payments-fallback")

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
                _a_candidate_answered_by(the_flag_that_worked_before, 0.9),
                _a_candidate_answered_by(the_flag_nobody_has_tried, 0.4)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([the_flag_that_worked_before, the_flag_nobody_has_tried]))


@pytest.mark.unit
def test_candidates_memory_says_nothing_about_keep_confidence_order() -> None:
    # The ordinary case, and the one that has to be exactly what it would have
    # been with no memory at all - otherwise "with memory" and "without" differ
    # in more than the one thing the benchmark is comparing.
    a_flag = an_identity("new-checkout-flow")
    another_flag = an_identity("payments-fallback")
    a_third_flag = an_identity("search-rerank")

    Scenario() \
        .given(nothing_like_this_has_happened := [a_remembered_incident(tried=[])]) \
        .when(lambda: demoting_what_was_refuted(
            [
                _a_candidate_answered_by(a_flag, 0.9),
                _a_candidate_answered_by(another_flag, 0.6),
                _a_candidate_answered_by(a_third_flag, 0.4)
            ],
            nothing_like_this_has_happened
        )) \
        .then(_the_order_is([a_flag, another_flag, a_third_flag]))


@pytest.mark.unit
def test_nothing_remembered_at_all_changes_nothing() -> None:
    # A cold store, a corpus with no match above the floor, and a store that
    # could not be reached all arrive here as the same empty list - and all
    # three have to leave the walk exactly as they found it.
    a_flag = an_identity("new-checkout-flow")
    another_flag = an_identity("payments-fallback")

    Scenario() \
        .given(nothing_was_recalled := cast(list[RememberedIncident], [])) \
        .when(lambda: demoting_what_was_refuted(
            [
                _a_candidate_answered_by(a_flag, 0.9),
                _a_candidate_answered_by(another_flag, 0.4)
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
    a_flag = an_identity("new-checkout-flow")
    another_flag = an_identity("payments-fallback")

    Scenario() \
        .given(
            both_failed_before := [
                a_remembered_incident(tried=[(a_flag, Verdict.REFUTED),
                                             (another_flag, Verdict.REFUTED)])
            ]
        ) \
        .when(lambda: demoting_what_was_refuted(
            [
                _a_candidate_answered_by(a_flag, 0.9),
                _a_candidate_answered_by(another_flag, 0.4)
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
    the_flag_that_failed_before = an_identity("new-checkout-flow")

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
                _a_candidate_answered_by(the_flag_that_failed_before, 0.9),
                _a_candidate_answered_by(an_identity("payments-fallback"), 0.4)
            ],
            what_happened_before
        )) \
        .then(all_of(
            _it_was_reordered_on(the_incident_that_settled_it),
            _what_moved_was(the_flag_that_failed_before)
        ))


@pytest.mark.unit
def test_a_candidate_nothing_would_be_done_about_is_left_where_it_is() -> None:
    # An explanation no action answers - no strategy for the cause, or one that
    # found nothing to act on. Memory has nothing to match it against, and
    # moving it would be moving it for no reason anybody could read back.
    the_flag_that_failed_before = an_identity("new-checkout-flow")

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
                _a_candidate_answered_by(None, 0.9),
                _a_candidate_answered_by(the_flag_that_failed_before, 0.6)
            ],
            what_happened_before
        )) \
        .then(_the_order_is([None, the_flag_that_failed_before]))


def _a_candidate_answered_by(identity: ActionIdentity | None,
                             confidence: float) -> WhatWouldBeTried:
    """One candidate, beside the action that answers it.

    Every candidate here carries the same subject, and it is deliberate: what
    the ordering compares is the action, so a builder that let the candidate's
    own words agree with the identity would pass whether or not the right one
    was read.
    """
    return WhatWouldBeTried(
        candidate=a_hypothesis(subject=DONT_CARE_SUBJECT, confidence=confidence),
        identity=identity
    )


def _the_order_is(expected: list[ActionIdentity | None]) -> Assertion[Reordering]:
    def assertion(reordered: Reordering) -> bool:
        identities = [entry.identity for entry in reordered.candidates]

        if identities != expected:
            raise AssertionError(f"expected {expected}, got {identities}")

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


def _what_moved_was(expected: ActionIdentity) -> Assertion[Reordering]:
    def assertion(reordered: Reordering) -> bool:
        if reordered.moved != expected:
            raise AssertionError(f"expected [{expected}] moved, got [{reordered.moved}]")

        return True

    return assertion
