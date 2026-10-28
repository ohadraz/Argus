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
from typing import TypedDict, Unpack

import pytest
from agent_postmortem.reviewing import (
    ANALYSIS_COMPLETE,
    IMPACT_ASSESSED,
    ITEMS_OWNED_AND_DATED,
    KEY_DATA_COLLECTED,
    REVIEWED_AND_SHARED,
    review_of,
)
from agent_postmortem.sections import TRIED_NOT_JUDGED
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChainStep,
    ChannelReading,
    CitedChange,
    CitedEvidence,
    ContributingFactor,
    Detection,
    HypothesisConsidered,
    Impact,
    Lessons,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    Refusal,
    ResolutionStep,
    ReviewCriterion,
    RuledOut,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Verdict,
    why_it_was_refused,
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
def test_key_data_is_not_collected_while_something_ruled_out_cites_nothing() -> None:
    # Held to what a step is: what the chain ruled out rests on evidence too.
    Scenario() \
        .given(
            a_document_with_an_uncited_ruling := _a_document(causal_chain=[
                ChainStep(text="the divisor was zero",
                          cites=[CitedEvidence(label="E1", text="dont care")],
                          ruled_out=[RuledOut(text="the earlier deploy", cites=[])])
            ])
        ) \
        .when(
            lambda: review_of(a_document_with_an_uncited_ruling, faults=[SOME_FAULT],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(KEY_DATA_COLLECTED, met=False,
                          because="something the causal chain ruled out cites nothing")
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
def test_impact_measured_to_a_close_the_service_was_not_back_by_is_left_for_a_person() -> None:
    # The loss was measured, and Argus stopped with the service still not back:
    # when it is back is not something the document can learn, and a person
    # reports it. A cross would say the document fell short where it could not
    # have done more.
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
            _says_because(IMPACT_ASSESSED, met=None,
                          because="the loss is measured to the close; when the service is "
                                  "back to normal is for a person to report")
        )


@pytest.mark.unit
def test_impact_measured_where_the_metrics_stopped_is_left_for_a_person() -> None:
    # The end is unknown because nothing measured it, and nothing will until
    # the metrics resume - which is a person's to see.
    Scenario() \
        .given(
            a_document_whose_metrics_stopped := _a_document(timeline=[
                _a_marker(TimelineMarker.METRICS_STOP)
            ])
        ) \
        .when(
            lambda: review_of(a_document_whose_metrics_stopped, faults=[],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(IMPACT_ASSESSED, met=None,
                          because="the loss is measured to the close; how long the metrics "
                                  "stay missing is known once they resume")
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
def test_a_candidate_never_tried_for_a_reason_is_still_one_nobody_tried() -> None:
    # Its row says why the test was held back; read as a verdict, the reason
    # made a candidate nobody tested one that was tried and came to nothing.
    Scenario() \
        .given(
            a_document_trying_nothing := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result="never tried: some reason", label="C1")
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
@pytest.mark.parametrize("result", ["action not taken", "action not taken: some reason"])
def test_a_candidate_whose_action_was_not_taken_is_still_one_nobody_tried(result: str) -> None:
    # Its action was reached for and ended before its write, so nothing was
    # changed and nothing tested it. Said apart from "never tried" on its row,
    # and counted with it here: read as a verdict, it would make a cause nobody
    # tested one that was tried and came to nothing.
    Scenario() \
        .given(
            a_document_trying_nothing := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result=result, label="C1")
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
@pytest.mark.parametrize("result", ["not known whether tried", "tried, no verdict recorded"])
def test_a_candidate_whose_change_may_have_been_made_is_not_one_nobody_tried(
        result: str) -> None:
    # Its change was made, or nobody can say it was not - so "none was tried"
    # would tell a reader the service was left alone.
    Scenario() \
        .given(
            a_document_trying_something := _a_document(hypotheses=[
                HypothesisConsidered(summary="dont care", confidence=None,
                                     result=result, label="C1")
            ])
        ) \
        .when(
            lambda: review_of(a_document_trying_something, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False, because="no candidate was confirmed")
        )


@pytest.mark.unit
@pytest.mark.parametrize("refusal", [
    Refusal.WOULD_UNDO_A_MEANT_CHANGE,
    Refusal.NOT_A_GENERIC_MITIGATION,
    Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH,
    Refusal.SOMEBODY_ELSES_SERVICE,
    Refusal.NOTHING_COULD_CONFIRM_IT
], ids=lambda refusal: refusal.value)
def test_an_analysis_whose_leader_was_not_argus_s_to_test_says_why_and_is_left_for_a_person(
        refusal: Refusal) -> None:
    # Nothing was tried because the gate held the leading candidate back at a
    # boundary of Argus's. The analysis went as far as Argus may, and what is
    # left is a person's - which each refusal says in its own words, since
    # each sends a reader to a different next step. The words the timeline and
    # the candidate's row say it in: three spellings of one reason read as
    # three reasons.
    Scenario() \
        .given(
            a_document_refused_its_test := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")],
                resolution=[_a_refusal(refusal)])
        ) \
        .when(
            lambda: review_of(a_document_refused_its_test, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None, because=why_it_was_refused(refusal))
        )


@pytest.mark.unit
def test_an_analysis_whose_leader_s_test_is_recommended_names_the_item_it_is_done_under() -> None:
    # The person's step is the recommended action, and the review says which
    # item that is, as it names the proposed fix's.
    some_recommendation = "Roll back io-shop"

    Scenario() \
        .given(
            a_document_recommending_its_test := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")],
                resolution=[_a_refusal(Refusal.NOTHING_COULD_CONFIRM_IT)],
                recommended_action=some_recommendation,
                action_items=[ActionItem(number="AI-1", text=some_recommendation,
                                         type=ActionItemType.MITIGATE, owner=None,
                                         tracking=None, status=ActionItemStatus.OPEN)])
        ) \
        .when(
            lambda: review_of(a_document_recommending_its_test, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None,
                          because=f"{why_it_was_refused(Refusal.NOTHING_COULD_CONFIRM_IT)} "
                                  f"(AI-1)")
        )


@pytest.mark.unit
def test_an_analysis_with_faults_beside_a_held_test_says_both() -> None:
    # A fault kept in the answer cost the review the reason the leader's test
    # was held back, and the item its next step is done under.
    Scenario() \
        .given(
            a_document_refused_its_test := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")],
                resolution=[_a_refusal(Refusal.NOTHING_COULD_CONFIRM_IT)])
        ) \
        .when(
            lambda: review_of(a_document_refused_its_test, faults=["dont care"],
                              reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because=f"the answer still had faults the checks found; "
                                  f"{why_it_was_refused(Refusal.NOTHING_COULD_CONFIRM_IT)}")
        )


@pytest.mark.unit
def test_an_analysis_whose_leader_was_short_of_evidence_is_not_complete_whatever_came_after(
) -> None:
    # The walk tests the leading candidate first. With no mitigation proposed
    # for it, it moves on, and a later candidate held back at a boundary does
    # not make the leader's shortfall a person's.
    Scenario() \
        .given(
            a_document_short_on_its_leader := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1"),
                            HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C2")],
                resolution=[_a_refusal(Refusal.NO_MITIGATION_PROPOSED),
                            _a_refusal(Refusal.NOT_A_GENERIC_MITIGATION)])
        ) \
        .when(
            lambda: review_of(a_document_short_on_its_leader, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=False,
                          because="no candidate was confirmed - none was tried")
        )


@pytest.mark.unit
def test_a_test_refused_as_not_argus_s_names_the_proposed_fix_that_would_confirm_it() -> None:
    some_fix = OpenedPullRequest(number=7, url="https://github.com/acme/shop/pull/7",
                                 branch="dont care")

    Scenario() \
        .given(
            a_document_with_a_fix := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")],
                resolution=[_a_refusal(Refusal.WOULD_UNDO_A_MEANT_CHANGE)],
                pull_request=some_fix,
                action_items=[ActionItem(number="AI-1", text="dont care",
                                         type=ActionItemType.MITIGATE, owner=None,
                                         tracking=some_fix.url,
                                         status=ActionItemStatus.OPEN)])
        ) \
        .when(
            lambda: review_of(a_document_with_a_fix, faults=[], reaches_a_cause=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None,
                          because=f"{why_it_was_refused(Refusal.WOULD_UNDO_A_MEANT_CHANGE)}; "
                                  f"the proposed fix would confirm the candidate (AI-1)")
        )


@pytest.mark.unit
def test_an_analysis_with_no_mitigation_proposed_is_still_not_complete() -> None:
    # Nothing proposed is evidence missing, not a boundary Argus held: the
    # analysis fell short.
    Scenario() \
        .given(
            a_document_that_proposed_nothing := _a_document(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="never tried", label="C1")],
                resolution=[_a_refusal(Refusal.NO_MITIGATION_PROPOSED)])
        ) \
        .when(
            lambda: review_of(a_document_that_proposed_nothing, faults=[], reaches_a_cause=True)
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
@pytest.mark.parametrize("results", [[Verdict.STOPPED], [Verdict.REFUTED, Verdict.STOPPED],
                                     [TRIED_NOT_JUDGED]],
                         ids=["stopped", "refuted-and-stopped", "tried-not-judged"])
def test_an_analysis_whose_tries_came_to_no_verdict_says_only_that_none_was_confirmed(
        results: list[str]) -> None:
    # A candidate whose test a person's ending stopped was tried all the same,
    # so "none was tried" is false of it - and "those tried were refuted" is
    # false of a set where one came to no verdict.
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


@pytest.mark.unit
def test_a_cause_the_answer_says_rests_on_an_unrun_reading_is_left_for_a_person() -> None:
    # Cited beside a line showing the error, the reading still carried the
    # mechanism alone: the box was ticked beside a root cause calling the cause
    # unverified. Whether the line shows the mechanism is the model's to judge,
    # so the box follows its answer.
    Scenario() \
        .given(
            a_document_citing_a_reading_beside_the_error := _a_document(causal_chain=[
                _a_step("account pages failed"),
                ChainStep(text="the divisor was zero",
                          cites=[CitedEvidence(label="F1", text="dont care"),
                                 CitedEvidence(label="G1", text="dont care")])
            ])
        ) \
        .when(
            lambda: review_of(a_document_citing_a_reading_beside_the_error, faults=[],
                              reaches_a_cause=True, rests_on_an_unrun_reading=True)
        ) \
        .then(
            _says_because(ANALYSIS_COMPLETE, met=None,
                          because="the cause rests on F1, a reading of the source nothing ran")
        )


@pytest.mark.unit
def test_a_cause_the_answer_says_rests_on_more_than_a_reading_is_judged_on_the_rest() -> None:
    # A step citing a reading alone, which the model says something it read
    # bears out - a diff or a file as it ran shows what the reading says.
    Scenario() \
        .given(
            a_document_resting_on_a_reading := _a_document(causal_chain=[
                _a_step("account pages failed"),
                ChainStep(text="the divisor was zero",
                          cites=[CitedEvidence(label="F1", text="dont care")])
            ])
        ) \
        .when(
            lambda: review_of(a_document_resting_on_a_reading, faults=[],
                              reaches_a_cause=True, rests_on_an_unrun_reading=False)
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


def _a_refusal(refusal: Refusal) -> ResolutionStep:
    return ResolutionStep(at=SOME_MOMENT, action="dont care", by="Argus", has_a_way_back=False,
                          outcome="not taken", label=None, refused=refusal)


class _WhatADocumentHolds(TypedDict, total=False):
    """Every field of a postmortem document, each typed as the model types it.

    Typed rather than `Any`, so mypy checks every name and value a case passes
    against this list, and this list against the model's own constructor: a
    field renamed in the model fails the typecheck here rather than being
    dropped while the case goes on asserting against the default.
    """

    root_cause: str | None
    executive_summary: str | None
    symptom: str | None
    customer_loss_estimate: Decimal | None
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    responder_titles: list[str]
    responder_cost_estimate: Decimal | None
    responder_cost_minimum: Decimal | None
    responder_cost_maximum: Decimal | None
    responder_cost_currency: str | None
    tokens_spent: int | None
    assumptions: list[str]
    pull_request: OpenedPullRequest | None
    recommended_action: str | None
    leads: list[PostmortemLead]
    impact: Impact | None
    detection: Detection | None
    trigger: Trigger | None
    resolution: list[ResolutionStep]
    causal_chain: list[ChainStep]
    contributing_factors: list[ContributingFactor]
    hypotheses: list[HypothesisConsidered]
    action_items: list[ActionItem]
    lessons: Lessons | None
    timeline: list[TimelineEntry]
    changes_read: list[CitedChange]
    log_messages_read: list[CitedEvidence]
    deployment_changes_read: list[CitedEvidence]
    code_read: list[CitedEvidence]
    deploys_reading: ChannelReading | None
    flags_reading: ChannelReading | None
    logs_reading: ChannelReading | None
    review: list[ReviewCriterion]


def _a_document(**overrides: Unpack[_WhatADocumentHolds]) -> PostmortemDocument:
    """A document that meets every criterion it can, but for what a test says."""
    complete: _WhatADocumentHolds = {
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

    return PostmortemDocument(**(complete | overrides))
