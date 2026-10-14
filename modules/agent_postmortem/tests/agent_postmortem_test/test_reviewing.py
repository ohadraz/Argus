"""Google's five review criteria, as far as a document can check itself.

Three are about what the document holds and are checked here. Two - every
action item owned and dated, and the document reviewed and shared - are
things people do, and are left to them rather than marked failed: a box
that is always unticked teaches its reader to stop looking at the boxes.
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
    ChainStep,
    CitedEvidence,
    HypothesisConsidered,
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
            lambda: review_of(a_complete_document, faults=[])
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
            lambda: review_of(a_document_with_no_timeline, faults=[])
        ) \
        .then(
            _says(KEY_DATA_COLLECTED, met=False)
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
            lambda: review_of(a_document_with_an_uncited_step, faults=[SOME_FAULT])
        ) \
        .then(
            _says(KEY_DATA_COLLECTED, met=False)
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
            lambda: review_of(a_document_with_no_loss, faults=[])
        ) \
        .then(
            _says(IMPACT_ASSESSED, met=False)
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
            lambda: review_of(a_document_that_never_saw_recovery, faults=[])
        ) \
        .then(
            _says(IMPACT_ASSESSED, met=False)
        )


@pytest.mark.unit
def test_an_analysis_of_one_step_is_not_complete() -> None:
    # One step is the symptom restated. The analysis is the steps below it.
    Scenario() \
        .given(
            a_document_with_one_step := _a_document(causal_chain=[_a_step("account pages failed")])
        ) \
        .when(
            lambda: review_of(a_document_with_one_step, faults=[])
        ) \
        .then(
            _says(ANALYSIS_COMPLETE, met=False)
        )


@pytest.mark.unit
def test_an_analysis_the_answer_still_had_faults_in_is_not_complete() -> None:
    Scenario() \
        .given(
            a_complete_document := _a_document()
        ) \
        .when(
            lambda: review_of(a_complete_document, faults=[SOME_FAULT])
        ) \
        .then(
            all_of(
                _says(ANALYSIS_COMPLETE, met=False),
                _says(KEY_DATA_COLLECTED, met=True)
            )
        )


@pytest.mark.unit
def test_an_analysis_that_confirmed_no_cause_is_not_complete() -> None:
    # A chain of steps can end on a cause nothing confirmed. The document then
    # says, rightly, that it is not a confirmed cause - and a ticked box beside
    # it says the opposite.
    Scenario() \
        .given(
            a_document_confirming_nothing := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result="never tried", label="C1")
            ])
        ) \
        .when(
            lambda: review_of(a_document_confirming_nothing, faults=[])
        ) \
        .then(
            _says(ANALYSIS_COMPLETE, met=False)
        )


def _says(criterion: str, met: bool | None) -> Assertion[list[ReviewCriterion]]:
    def assertion(review: list[ReviewCriterion]) -> bool:
        said = [entry.met for entry in review if entry.criterion == criterion]

        if said != [met]:
            raise AssertionError(
                f"Expected the review to say [{criterion}] once, as {met}, got {said}.")

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
