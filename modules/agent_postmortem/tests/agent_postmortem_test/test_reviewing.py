"""Google's five review criteria, as far as a document can check itself.

Three are about what the document holds and are checked here. Two - every
action item owned and dated, and the document reviewed and shared - are
things people do, and are left to them rather than marked failed: a box
that is always unticked teaches its reader to stop looking at the boxes.

A criterion not met says why under it, as one left for a person does: a cross
with nothing beside it says only that something somewhere fell short.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem.reviewing import (
    ANALYSIS_COMPLETE,
    IMPACT_ASSESSED,
    ITEMS_OWNED_AND_DATED,
    KEY_DATA_COLLECTED,
    REVIEWED_AND_SHARED,
    review_of,
)
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChainStep,
    CitedEvidence,
    HypothesisConsidered,
    OpenedPullRequest,
    PostmortemDocument,
    ReviewCriterion,
    TimelineEntry,
    TimelineMarker,
    Verdict,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

SOME_MOMENT = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)
SOME_FAULT = "the step [the divisor was zero] cites no evidence"


@pytest.mark.unit
def test_a_document_with_everything_meets_all_three_and_leaves_two_to_people() -> None:
    Scenario() \
        .given(
            a_complete_document := _a_document()
        ) \
        .when(
            lambda: review_of(a_complete_document, faults=[], reaches_a_cause=True)
        ) \
        .then(
            the_answer_was([
                ReviewCriterion(criterion=KEY_DATA_COLLECTED, met=True),
                ReviewCriterion(criterion=IMPACT_ASSESSED, met=True),
                ReviewCriterion(criterion=ANALYSIS_COMPLETE, met=True),
                ReviewCriterion(criterion=ITEMS_OWNED_AND_DATED, met=None),
                ReviewCriterion(criterion=REVIEWED_AND_SHARED, met=None)
            ])
        )


@pytest.mark.unit
def test_key_data_is_not_collected_without_a_timeline() -> None:
    Scenario() \
        .given(
            a_document_with_no_timeline := _a_document(timeline=[])
        ) \
        .when(
            lambda: review_of(a_document_with_no_timeline, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(KEY_DATA_COLLECTED, met=False, because="there is no timeline")
        )


@pytest.mark.unit
def test_key_data_is_not_collected_while_a_step_cites_nothing() -> None:
    Scenario() \
        .given(
            a_document_with_an_uncited_step := _a_document(causal_chain=[
                ChainStep(text="the divisor was zero", cites=[])
            ])
        ) \
        .when(
            lambda: review_of(a_document_with_an_uncited_step, faults=[SOME_FAULT],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(KEY_DATA_COLLECTED, met=False,
                          because="a step of the causal chain cites nothing")
        )


@pytest.mark.unit
def test_impact_is_not_assessed_without_a_loss_figure() -> None:
    # Explained among the assumptions, and still not assessed: the criterion
    # is whether the reader knows what it cost, not whether the gap is excused.
    Scenario() \
        .given(
            a_document_with_no_loss := _a_document(customer_loss_estimate=None)
        ) \
        .when(
            lambda: review_of(a_document_with_no_loss, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(IMPACT_ASSESSED, met=False, because="no loss was estimated")
        )


@pytest.mark.unit
def test_impact_is_not_assessed_while_the_end_of_it_is_unknown() -> None:
    # A duration that is a lower bound is impact not yet measured.
    Scenario() \
        .given(
            a_document_that_never_saw_recovery := _a_document(timeline=[
                _a_marker(TimelineMarker.IMPACT_BEGINS)
            ])
        ) \
        .when(
            lambda: review_of(a_document_that_never_saw_recovery, faults=[],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(IMPACT_ASSESSED, met=False,
                          because="the service was never seen back to normal")
        )


@pytest.mark.unit
def test_impact_short_twice_over_says_both() -> None:
    Scenario() \
        .given(
            a_document_short_twice_over := _a_document(
                customer_loss_estimate=None,
                timeline=[_a_marker(TimelineMarker.IMPACT_BEGINS)])
        ) \
        .when(
            lambda: review_of(a_document_short_twice_over, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(IMPACT_ASSESSED, met=False,
                          because="no loss was estimated; the service was never seen back "
                                  "to normal")
        )


@pytest.mark.unit
def test_an_analysis_of_one_step_is_not_complete() -> None:
    # One step is the symptom restated. The analysis is the steps below it.
    Scenario() \
        .given(
            a_document_with_one_step := _a_document(causal_chain=[_a_step("account pages failed")])
        ) \
        .when(
            lambda: review_of(a_document_with_one_step, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because="the causal chain stops at the symptom")
        )


@pytest.mark.unit
def test_an_analysis_the_answer_still_had_faults_in_is_not_complete() -> None:
    Scenario() \
        .given(
            a_complete_document := _a_document()
        ) \
        .when(
            lambda: review_of(a_complete_document, faults=[SOME_FAULT], reaches_a_cause=True)
        ) \
        .then(
            all_of(
                _says_because(ANALYSIS_COMPLETE, met=False,
                              because="the answer still had faults the checks found"),
                _says(KEY_DATA_COLLECTED, met=True)
            )
        )


@pytest.mark.unit
def test_an_analysis_that_tried_no_candidate_is_not_complete() -> None:
    # A chain of steps can end on a cause nothing confirmed. The document then
    # says, rightly, that it is not a confirmed cause - and a ticked box beside
    # it says the opposite.
    Scenario() \
        .given(
            a_document_trying_nothing := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result="never tried", label="C1")
            ])
        ) \
        .when(
            lambda: review_of(a_document_trying_nothing, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because="no candidate was confirmed - none was tried")
        )


@pytest.mark.unit
def test_an_analysis_whose_candidates_were_refuted_is_not_complete() -> None:
    Scenario() \
        .given(
            a_document_refuting_its_candidates := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result=Verdict.REFUTED, label="C1"),
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result="never tried", label="C2")
            ])
        ) \
        .when(
            lambda: review_of(a_document_refuting_its_candidates, faults=[],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because="no candidate was confirmed - those tried were refuted")
        )


@pytest.mark.unit
@pytest.mark.parametrize("results", [[Verdict.WITHDRAWN], [Verdict.REFUTED, Verdict.WITHDRAWN]],
                         ids=["withdrawn", "refuted-and-withdrawn"])
def test_an_analysis_whose_tries_came_to_no_verdict_says_only_that_none_was_confirmed(
        results: list[str]) -> None:
    # A candidate withdrawn was tried all the same, so "none was tried" is
    # false of it - and "those tried were refuted" is false of a set where one
    # came to no verdict.
    Scenario() \
        .given(
            a_document_trying_to_no_end := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None, result=result,
                                     label=f"C{place}")
                for place, result in enumerate(results, start=1)])
        ) \
        .when(
            lambda: review_of(a_document_trying_to_no_end, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False, because="no candidate was confirmed")
        )


@pytest.mark.unit
def test_an_analysis_that_stops_at_the_change_that_set_it_off_is_not_complete() -> None:
    # A rollback can confirm which change set the incident off and say nothing
    # of why that change broke the service. A chain ending on the change is a
    # trigger found, not a cause, and the model's own answer is what says so.
    Scenario() \
        .given(
            a_complete_document := _a_document()
        ) \
        .when(
            lambda: review_of(a_complete_document, faults=[], reaches_a_cause=False)
        ) \
        .then(
            all_of(
                _says_because(ANALYSIS_COMPLETE, met=False,
                              because="the chain does not reach a cause beyond the change "
                                      "that set it off"),
                _says(KEY_DATA_COLLECTED, met=True)
            )
        )


@pytest.mark.unit
def test_an_analysis_short_in_several_ways_says_each_in_the_order_checked() -> None:
    Scenario() \
        .given(
            a_document_short_every_way := _a_document(
                causal_chain=[_a_step("account pages failed")],
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")])
        ) \
        .when(
            lambda: review_of(a_document_short_every_way, faults=[SOME_FAULT],
                              reaches_a_cause=False)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because="the answer still had faults the checks found; the causal "
                                  "chain stops at the symptom; no candidate was confirmed - "
                                  "none was tried; the chain does not reach a cause beyond the "
                                  "change that set it off")
        )


@pytest.mark.unit
def test_an_analysis_resting_on_a_reading_nothing_ran_is_left_for_a_person() -> None:
    # Code-Fix read the source and nothing ran it, so a step resting on that
    # reading alone is a mechanism proposed rather than confirmed: the document
    # says so in its words, and a ticked box beside it says the opposite. Not
    # failed either - the analysis went as far as the evidence allowed, and
    # what is left is a task for a person: running the reading.
    Scenario() \
        .given(
            a_document_resting_on_a_reading := _a_document(causal_chain=[
                _a_step("account pages failed"),
                ChainStep(text="the divisor was zero",
                          cites=[CitedEvidence(label="F1", text="dont care")])
            ])
        ) \
        .when(
            lambda: review_of(a_document_resting_on_a_reading, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None,
                          because="the cause rests on F1, a reading of the source nothing ran")
        )


@pytest.mark.unit
def test_a_reading_a_proposed_fix_can_confirm_names_the_item_that_would() -> None:
    # Where Code-Fix proposed a fix, its tests run against the code as it is
    # are what would confirm the reading, and the item tracking the fix is
    # where a person does it.
    some_fix = OpenedPullRequest(number=7, url="https://github.invalid/acme/shop/pull/7",
                                 branch="argus/fix")

    Scenario() \
        .given(
            a_document_with_a_fix := _a_document(
                causal_chain=[_a_step("account pages failed"),
                              ChainStep(text="the divisor was zero",
                                        cites=[CitedEvidence(label="F1", text="dont care")])],
                pull_request=some_fix,
                action_items=[ActionItem(number="AI-2", text="dont care",
                                         type=ActionItemType.PREVENT, owner=None,
                                         tracking=some_fix.url,
                                         status=ActionItemStatus.OPEN)])
        ) \
        .when(
            lambda: review_of(a_document_with_a_fix, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None,
                          because="the cause rests on F1, a reading of the source nothing ran; "
                                  "running the proposed fix's tests against the current code "
                                  "would confirm it (AI-2)")
        )


@pytest.mark.unit
def test_a_step_a_reading_and_an_observation_both_support_is_supported() -> None:
    # A reading beside something observed is evidence the observation bears
    # out, and the step rests on more than the reading.
    Scenario() \
        .given(
            a_document_with_a_supported_reading := _a_document(causal_chain=[
                _a_step("account pages failed"),
                ChainStep(text="the divisor was zero",
                          cites=[CitedEvidence(label="F1", text="dont care"),
                                 CitedEvidence(label="E1", text="dont care")])
            ])
        ) \
        .when(
            lambda: review_of(a_document_with_a_supported_reading, faults=[],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=True, because=None)
        )


def _says(criterion: str, met: bool | None) -> Assertion[list[ReviewCriterion]]:
    def assertion(review: list[ReviewCriterion]) -> bool:
        said = [entry.met for entry in review if entry.criterion == criterion]

        if said != [met]:
            raise AssertionError(
                f"Expected the review to say [{criterion}] once, as {met}, got {said}.")

        return True

    return assertion


def _says_because(criterion: str, met: bool | None,
                  because: str | None) -> Assertion[list[ReviewCriterion]]:
    def assertion(review: list[ReviewCriterion]) -> bool:
        said = [(entry.met, entry.because) for entry in review if entry.criterion == criterion]

        if said != [(met, because)]:
            raise AssertionError(
                f"Expected the review to say [{criterion}] once, as {met} because "
                f"[{because}], got {said}.")

        return True

    return assertion


def _a_step(text: str) -> ChainStep:
    return ChainStep(text=text, cites=[CitedEvidence(label="E1", text="dont care")])


def _a_marker(marker: TimelineMarker) -> TimelineEntry:
    return TimelineEntry(at=SOME_MOMENT, who=None, text="dont care", marker=marker)


def _a_document(**overrides: Any) -> PostmortemDocument:
    """A document that meets every criterion it can, but for what a test says."""
    complete: dict[str, Any] = {
        "root_cause": "dont care",
        "executive_summary": "dont care",
        "customer_loss_estimate": Decimal("500"),
        "estimate_currency": "usd",
        "engineer_minutes": None,
        "responders": None,
        "tokens_spent": None,
        "assumptions": [],
        "causal_chain": [_a_step("account pages failed"), _a_step("the divisor was zero")],
        "timeline": [_a_marker(TimelineMarker.IMPACT_BEGINS),
                     _a_marker(TimelineMarker.IMPACT_ENDS)],
        "hypotheses": [HypothesisConsidered(summary="dont care", confidence=None,
                                            result=Verdict.CONFIRMED, label="C1")]
    }

    return PostmortemDocument(**{**complete, **overrides})
