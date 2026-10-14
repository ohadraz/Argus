"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each.

Each case is one postmortem and the table the section says it as.
"""

from __future__ import annotations

import pytest
from argus_core.models import HypothesisConsidered
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.hypotheses import HypothesisRow, the_hypotheses

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_each_candidate_is_a_row_with_its_confidence_to_two_places() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(summary="a flag change on account pages", confidence=0.8,
                                     result="confirmed", label="C1"),
                HypothesisConsidered(summary="a bad deploy", confidence=None,
                                     result="never tried", label="C2")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows
        ) \
        .then(
            the_answer_was((
                HypothesisRow(label="C1", summary="a flag change on account pages",
                              confidence="0.80", result="confirmed"),
                HypothesisRow(label="C2", summary="a bad deploy",
                              confidence="-", result="never tried"))))


@pytest.mark.unit
def test_the_table_names_its_columns() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_hypotheses(dont_care_postmortem).headings
        ) \
        .then(
            the_answer_was(("", "Hypothesis", "Confidence", "Result")))


@pytest.mark.unit
def test_an_investigation_that_ranked_nothing_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).absent
        ) \
        .then(
            the_answer_was("No hypotheses were ranked."))


@pytest.mark.unit
def test_a_ranked_investigation_says_nothing_of_absence() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result="dont care", label="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).absent
        ) \
        .then(
            the_answer_was(None))
