"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - each revision it names said short, as the
rest of the document says it, and leading to its commit.

Each case is one postmortem and the table the section says it as.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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
    # A document written before the several were carried has the one row and
    # nothing to split it by.
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
def test_candidates_merged_in_the_record_are_each_a_row_of_their_own() -> None:
    # Two candidates on one row read as one claim, and one candidate's figures
    # shown as the row's own read as another's: a candidate never tried reads
    # as confirmed, at a confidence it never had. So each is a row like any
    # other - its own words and confidence - and the result of the one not
    # tried says whose test reached it.
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
                HypothesisRow(label="C1", summary=_said("The model was upgraded."),
                              confidence="0.70", result="confirmed"),
                HypothesisRow(label="C2", summary=_said("The values file was changed."),
                              confidence="0.20", result="confirmed, as tested for C1"))))


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
def test_an_instant_a_candidate_names_is_said_as_a_moment() -> None:
    # The candidate says it as the Investigator wrote it, in the wire format
    # its tools speak, and the rest of the document says the same instant as
    # a moment. Left so, one document says one instant two ways, and only one
    # of them is said again on a reader's own clock.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(summary="the deploy at 2026-10-16T10:55Z broke it",
                                     confidence=0.8, result="confirmed", label="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem).rows[0].summary
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="the deploy at "),
                Run.a_moment(datetime(2026, 10, 16, 10, 55, tzinfo=UTC)),
                Run(text=" broke it")))))


@pytest.mark.unit
def test_a_zoned_clock_time_a_candidate_names_is_said_as_a_moment_on_the_document_s_day() -> None:
    # The model writes a clock time with the wire's zone marker too - "served
    # stale at 19:29:35Z" - and it is put on the day the document is dated by,
    # as the page puts one on the day of its line.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(hypotheses=[
                HypothesisConsidered(summary="served stale at 19:29:35Z",
                                     confidence=0.8, result="confirmed", label="C1")])
        ) \
        .when(
            lambda: the_hypotheses(some_postmortem, day=date(2026, 10, 18)).rows[0].summary
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="served stale at "),
                Run.a_moment(datetime(2026, 10, 18, 19, 29, 35, tzinfo=UTC))))))


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
