"""What is wrong with an answer, asked of the answer itself.

The conversation beside this one asks the same questions through two model
turns, which is the right way to test the retry and the wrong way to test the
rule: a fault there is visible only as a second ask, so a rule that fired for
the wrong reason and a rule that fired for the right one read identically.
Here the answer goes in and the faults come out.

Two faults, and they are not alike. A required field the model left out is a
fact about the answer. A figure in the executive summary that Argus never
computed is a fact about the world the answer describes - the columns are safe
by construction, but the summary is published as written, so a fluent sentence
naming an invented number reaches the reader least able to check it.

Every case here asserts what was named, not how many faults came back. The
wording is the product: a model told "invalid answer" rewrites the part it
liked least, which is rarely the part that was wrong.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_postmortem.checking import faults_in
from agent_postmortem.prompting import (
    EXECUTIVE_SUMMARY_FIELD,
    ROOT_CAUSE_FIELD,
    SubmittedPostmortem,
)
from argus_testkit import Assertion, Scenario, all_of

# The figure this file's incident was measured at. A stated amount is only
# checkable against a computed one, so every summary below is read against
# this.
SOME_COMPUTED_LOSS = Decimal("500")

# The same figure said three ways. The tolerance is 5%, so 25 either side of
# 500 is the same figure loosely stated and anything past it is a different
# one - which is the distinction the check exists to make, and the reason
# these are literals rather than arithmetic on the constant. A tolerance
# narrowed to nothing should fail this file, not quietly re-derive it.
SOME_SUMMARY_STATING_THE_FIGURE = "the outage cost $500"
SOME_SUMMARY_STATING_IT_ROUGHLY = "the outage cost roughly $520"
SOME_SUMMARY_STATING_A_DIFFERENT_FIGURE = "the outage cost roughly $600"

SOME_INVENTED_FIGURE = "$1,200,000"
SOME_OTHER_INVENTED_FIGURE = "$4,300"
SOME_SUMMARY_WITHOUT_A_FIGURE = "checkout failed for half an hour"

DONT_CARE_PROSE = "dont care"


@pytest.mark.unit
def test_a_required_field_the_model_left_out_is_named() -> None:
    # Named rather than counted. The fault is handed back to the model as the
    # whole of its second chance, and a model told only that its answer was
    # wrong has nothing to correct.
    Scenario() \
        .given(
            an_answer_with_no_root_cause := SubmittedPostmortem(
                executive_summary=DONT_CARE_PROSE)
        ) \
        .when(
            lambda: faults_in(an_answer_with_no_root_cause, SOME_COMPUTED_LOSS)
        ) \
        .then(
            all_of(
                _named(ROOT_CAUSE_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
def test_every_required_field_missing_is_named_and_not_just_the_first() -> None:
    # A check that stopped at the first would spend the one retry on half the
    # problem, and the second answer would come back missing the other field
    # with no chances left.
    Scenario() \
        .given(
            an_answer_carrying_neither := SubmittedPostmortem()
        ) \
        .when(
            lambda: faults_in(an_answer_carrying_neither, SOME_COMPUTED_LOSS)
        ) \
        .then(
            all_of(
                _named(ROOT_CAUSE_FIELD),
                _named(EXECUTIVE_SUMMARY_FIELD),
                _found(2)
            )
        )


@pytest.mark.unit
def test_an_answer_carrying_what_was_required_has_nothing_wrong_with_it() -> None:
    # The accepting case, which is the one that decides whether the document
    # says it is complete.
    Scenario() \
        .given(
            a_complete_answer := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_WITHOUT_A_FIGURE)
        ) \
        .when(
            lambda: faults_in(a_complete_answer, SOME_COMPUTED_LOSS)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_field_the_tool_never_required_is_not_missed() -> None:
    # The model is asked for its assumptions and allowed to have none. A check
    # reading every field rather than the required ones would make an honest
    # empty answer into a fault, and spend the retry asking for it again.
    Scenario() \
        .given(
            an_answer_assuming_nothing := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_WITHOUT_A_FIGURE,
                assumptions=[])
        ) \
        .when(
            lambda: faults_in(an_answer_assuming_nothing, SOME_COMPUTED_LOSS)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_figure_the_summary_states_that_argus_never_computed_is_named() -> None:
    # The whole reason this check exists. Nothing downstream can tell that
    # "$1.2M" was invented: it is a fluent sentence in a document whose every
    # other number is measured.
    Scenario() \
        .given(
            an_answer_naming_a_figure_nobody_computed := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=f"the outage cost {SOME_INVENTED_FIGURE}")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_figure_nobody_computed,
                              SOME_COMPUTED_LOSS)
        ) \
        .then(
            all_of(
                _named(SOME_INVENTED_FIGURE),
                _found(1)
            )
        )


@pytest.mark.unit
def test_the_figure_argus_did_compute_may_be_stated() -> None:
    # The check is on figures Argus did not arrive at, not on figures. A
    # summary forbidden to mention what the incident cost would be a summary
    # written for nobody.
    Scenario() \
        .given(
            an_answer_stating_the_computed_figure := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_STATING_THE_FIGURE)
        ) \
        .when(
            lambda: faults_in(an_answer_stating_the_computed_figure,
                              SOME_COMPUTED_LOSS)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_the_computed_figure_stated_roughly_is_still_that_figure() -> None:
    # A summary saying "roughly $520" about an estimate of $500 is doing
    # exactly what a summary should. A check that failed it would teach the
    # next prompt to print the number to the cent, in the one field written
    # for a reader who does not want it.
    Scenario() \
        .given(
            an_answer_rounding_the_figure := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_STATING_IT_ROUGHLY)
        ) \
        .when(
            lambda: faults_in(an_answer_rounding_the_figure, SOME_COMPUTED_LOSS)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_figure_past_the_tolerance_is_a_different_figure() -> None:
    # The other side of the same line, and the reason the tolerance is a number
    # rather than a shrug: past it, a summary is no longer rounding what it was
    # given, it is stating something else.
    Scenario() \
        .given(
            an_answer_stating_something_else := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_STATING_A_DIFFERENT_FIGURE)
        ) \
        .when(
            lambda: faults_in(an_answer_stating_something_else,
                              SOME_COMPUTED_LOSS)
        ) \
        .then(
            _found(1)
        )


@pytest.mark.unit
def test_every_invented_figure_is_named_and_not_just_the_first() -> None:
    # A summary that made up two numbers is corrected once or not at all.
    # Naming one of them buys a second answer that fixes half a sentence.
    Scenario() \
        .given(
            an_answer_naming_two := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=(
                    f"the outage cost {SOME_INVENTED_FIGURE} in takings and "
                    f"{SOME_OTHER_INVENTED_FIGURE} in refunds"))
        ) \
        .when(
            lambda: faults_in(an_answer_naming_two, SOME_COMPUTED_LOSS)
        ) \
        .then(
            all_of(
                _named(SOME_INVENTED_FIGURE),
                _named(SOME_OTHER_INVENTED_FIGURE),
                _found(2)
            )
        )


@pytest.mark.unit
def test_with_nothing_computed_any_figure_at_all_is_invented() -> None:
    # There is nothing for a figure to agree with, so every figure is invented
    # by definition - which is the case whenever the payment provider or the
    # rate source could not be read. A summary is not licensed to fill that gap
    # with a number of its own.
    Scenario() \
        .given(
            an_answer_costing_an_incident_nobody_could_cost :=
                SubmittedPostmortem(
                    root_cause=DONT_CARE_PROSE,
                    executive_summary=SOME_SUMMARY_STATING_THE_FIGURE)
        ) \
        .when(
            lambda: faults_in(an_answer_costing_an_incident_nobody_could_cost,
                              None)
        ) \
        .then(
            _found(1)
        )


@pytest.mark.unit
def test_a_summary_that_states_no_figure_is_accepted_when_none_was_computed() -> None:
    # Saying nothing about the cost is the correct answer to an incident nobody
    # could cost, and it has to be an answer this accepts - otherwise there is
    # no summary the model could write that would pass.
    Scenario() \
        .given(
            an_answer_saying_nothing_about_money := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE,
                executive_summary=SOME_SUMMARY_WITHOUT_A_FIGURE)
        ) \
        .when(
            lambda: faults_in(an_answer_saying_nothing_about_money, None)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_summary_the_model_never_wrote_is_missing_rather_than_invented() -> None:
    # An absent summary has no figures in it, and the fault it earns is the one
    # about the field. Reporting both would put a contradiction to the model -
    # write less, and also write something.
    Scenario() \
        .given(
            an_answer_with_no_summary := SubmittedPostmortem(
                root_cause=DONT_CARE_PROSE)
        ) \
        .when(
            lambda: faults_in(an_answer_with_no_summary, SOME_COMPUTED_LOSS)
        ) \
        .then(
            all_of(
                _named(EXECUTIVE_SUMMARY_FIELD),
                _found(1)
            )
        )


def _named(expected: str) -> Assertion[list[str]]:
    """That some fault says the thing the model has to act on.

    Containment rather than equality: the sentence around it is written for a
    model and is free to be reworded, while the field or the figure inside it
    is the part a second attempt is about.
    """
    def assertion(faults: list[str]) -> bool:
        if not any(expected in fault for fault in faults):
            raise AssertionError(
                f"Expected a fault naming [{expected}], got {faults}.")

        return True

    return assertion


def _found(expected: int) -> Assertion[list[str]]:
    def assertion(faults: list[str]) -> bool:
        if len(faults) != expected:
            raise AssertionError(
                f"Expected [{expected}] fault(s), got [{len(faults)}]: {faults}.")

        return True

    return assertion


def _found_nothing_wrong() -> Assertion[list[str]]:
    def assertion(faults: list[str]) -> bool:
        if faults:
            raise AssertionError(
                f"Expected nothing wrong with the answer, got {faults}.")

        return True

    return assertion
