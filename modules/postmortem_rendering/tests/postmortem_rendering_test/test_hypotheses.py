"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - each revision it names said short, as the
rest of the document says it, and leading to its commit.

Each case is one postmortem and the table the section says it as.
"""

from __future__ import annotations

import pytest
from argus_core.models import CandidateConsidered, HypothesisConsidered
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.hypotheses import HypothesisRow, the_hypotheses
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import (
    SOME_DEPLOYED_REVISION,
    SOME_REPOSITORY_ADDRESS,
    a_deploy_read,
    a_postmortem,
)


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
                HypothesisRow(label="C1", summary=_said("a flag change on account pages"),
                              confidence="0.80", result="confirmed"),
                HypothesisRow(label="C2", summary=_said("a bad deploy"),
                              confidence="-", result="never tried"))))


@pytest.mark.unit
def test_a_row_standing_for_several_candidates_goes_by_each_of_their_labels() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(summary="the model was upgraded", confidence=0.8,
                                     result="confirmed", label="C1", also=["C2"])])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows
        ) \
        .then(
            the_answer_was((
                HypothesisRow(label="C1", also=("C2",), summary=_said("the model was upgraded"),
                              confidence="0.80", result="confirmed"),)))


@pytest.mark.unit
def test_a_row_standing_for_several_candidates_says_whose_each_figure_is() -> None:
    # One candidate's figures shown as the row's own read as another's: a
    # candidate never tried reads as confirmed, at a confidence it never had,
    # and its own claim is hidden. So each says its own words, mode and
    # confidence, and the result says whose test reached it - each claim on a
    # line of its own, since run together they read as one, and each mode in
    # plain words rather than the value the model was taught.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(
                    summary="The model was upgraded.", confidence=0.7, result="confirmed",
                    label="C1", also=["C2"],
                    members=[CandidateConsidered(label="C1", summary="The model was upgraded.",
                                                 confidence=0.7,
                                                 failure_mode="output-quality-degradation"),
                             CandidateConsidered(label="C2",
                                                 summary="The values file was changed.",
                                                 confidence=0.2,
                                                 failure_mode="config-induced-failure")],
                    decided_by="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows
        ) \
        .then(
            the_answer_was((
                HypothesisRow(label="C1", also=("C2",),
                              summary=Line(runs=(
                                  Run(text="C1 (a model answering worse): "),
                                  Run(text="The model was upgraded."),
                                  Run(text="\n"),
                                  Run(text="C2 (a bad configuration change): "),
                                  Run(text="The values file was changed."))),
                              confidence="0.70 (C1); 0.20 (C2)",
                              result="confirmed, as tested for C1"),)))


@pytest.mark.unit
def test_a_mode_no_longer_in_the_taxonomy_is_said_in_its_own_words() -> None:
    # A document outlives the taxonomy it was written against, and a mode since
    # retired still has to be printed as something a person reads.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(
                    summary="dont care", confidence=0.7, result="dont care", label="C1",
                    also=["C2"],
                    members=[CandidateConsidered(label="C1", summary="dont care", confidence=0.7,
                                                 failure_mode="some-retired-mode"),
                             CandidateConsidered(label="C2", summary="dont care either",
                                                 confidence=0.2, failure_mode=None)],
                    decided_by="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows[0].summary.runs[0]
        ) \
        .then(
            the_answer_was(Run(text="C1 (some retired mode): ")))


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_DEPLOYED_REVISION, SOME_DEPLOYED_REVISION[:8]],
                         ids=["whole", "by-a-start-of-it"])
def test_a_revision_a_candidate_names_is_said_short_and_leads_where_it_opens(named: str) -> None:
    # The candidate says it as the model wrote it - whole, mostly, or by as
    # much of it as the model liked - and the trigger and the timeline say it
    # short. Left so, one document names one revision two ways, and only one
    # of them opens.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[a_deploy_read("P2")],
                hypotheses=[HypothesisConsidered(summary=f"{named} made every page slow",
                                                 confidence=0.8, result="confirmed",
                                                 label="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows[0].summary
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK,
                    address=f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"),
                Run(text=" made every page slow")))))


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


def _said(summary: str) -> Line:
    """A candidate's words that name nothing that opens, as its row says them."""
    return Line(runs=(Run(text=summary),))
