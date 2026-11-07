"""The causal chain put in the order its whys answer each other.

The write-up is asked for the cause as the five whys, each step answering why
the one before it happened - and a write-up gave its steps in the wrong order
anyway, the step saying why the symptom happened coming after the one it
explains. A second ask, after the answer is accepted, puts them in order: by
their numbers only, so nothing a step says can change, and with the first and
the last held where they are - the first is the symptom, the last the root
cause, and both are said elsewhere in the document too.
"""

from __future__ import annotations

import pytest
from agent_postmortem.ordering import (
    ORDER_FIELD,
    ORDER_TOOL_NAME,
    in_its_order,
    ordering_asked,
    put_in_order,
)
from agent_postmortem.prompting import SubmittedStep
from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable
from argus_core.models import ToolDefinition, Transcript, Turn
from argus_testkit import Assertion, Scenario, the_answer_was

from agent_postmortem_test.framework.builders import (
    a_model_answering_in_turn,
    a_submission_of,
)

SOME_CHAIN = [
    SubmittedStep(step="no metrics arrived", cites=["T5"]),
    SubmittedStep(step="the scrape had no target", cites=["F1"]),
    SubmittedStep(step="the name it selects matches no port", cites=["D1"]),
    SubmittedStep(step="the rename reached one file only", cites=["P2"])
]


@pytest.mark.unit
def test_an_order_keeping_the_first_and_last_step_is_the_chain_s_order() -> None:
    Scenario() \
        .when(
            lambda: in_its_order(SOME_CHAIN, _an_order(1, 3, 2, 4))
        ) \
        .then(
            the_answer_was([SOME_CHAIN[0], SOME_CHAIN[2], SOME_CHAIN[1], SOME_CHAIN[3]])
        )


@pytest.mark.unit
@pytest.mark.parametrize("order", [(2, 1, 3, 4), (1, 2, 4, 3)],
                         ids=["first-moved", "last-moved"])
def test_an_order_moving_the_first_or_last_step_leaves_the_chain_as_written(
        order: tuple[int, ...]) -> None:
    # The first step agrees with the symptom and the last with the root cause,
    # which the document says on their own: moved, the three would disagree.
    Scenario() \
        .when(
            lambda: in_its_order(SOME_CHAIN, _an_order(*order))
        ) \
        .then(
            the_answer_was(SOME_CHAIN)
        )


@pytest.mark.unit
@pytest.mark.parametrize("order", [(1, 2, 2, 4), (1, 3, 4), (1, 3, 2, 4, 5), (1, 5, 2, 4)],
                         ids=["a-step-twice", "a-step-left-out", "a-step-added",
                              "a-step-that-is-none"])
def test_an_order_that_is_not_the_same_steps_rearranged_leaves_the_chain_as_written(
        order: tuple[int, ...]) -> None:
    # Only a rearrangement is taken: anything else would drop a step the model
    # wrote, or say one twice.
    Scenario() \
        .when(
            lambda: in_its_order(SOME_CHAIN, _an_order(*order))
        ) \
        .then(
            the_answer_was(SOME_CHAIN)
        )


@pytest.mark.unit
@pytest.mark.parametrize("order", [[1, "3", 2, 4], [1, 3.0, 2, 4], [True, 3, 2, 4]],
                         ids=["a-string", "a-float", "a-flag"])
def test_an_order_naming_a_step_by_anything_but_a_whole_number_leaves_the_chain_as_written(
        order: list[object]) -> None:
    # A string among numbers cannot be sorted, and a float that equals its
    # step's number passes every comparison and then fails as an index - either
    # way the accepted write-up was lost to a suggestion about its order.
    Scenario() \
        .when(
            lambda: in_its_order(SOME_CHAIN, a_submission_of({ORDER_FIELD: order},
                                                             ORDER_TOOL_NAME))
        ) \
        .then(
            the_answer_was(SOME_CHAIN)
        )


@pytest.mark.unit
def test_an_answer_naming_no_order_leaves_the_chain_as_written() -> None:
    Scenario() \
        .when(
            lambda: in_its_order(SOME_CHAIN, a_submission_of({}, ORDER_TOOL_NAME))
        ) \
        .then(
            the_answer_was(SOME_CHAIN)
        )


@pytest.mark.unit
def test_the_steps_are_asked_about_by_number_and_the_rule_they_are_ordered_by() -> None:
    Scenario() \
        .when(
            lambda: ordering_asked(SOME_CHAIN)
        ) \
        .then(
            _says("1. no metrics arrived", "4. the rename reached one file only",
                  "each step answers why the step directly before it happened",
                  "the first and the last stay where they are")
        )


@pytest.mark.unit
def test_a_chain_too_short_to_reorder_is_not_asked_about() -> None:
    # With both ends held, a chain of three has one step that could move and
    # nowhere for it to go. The model is asked nothing - it would fail the
    # test, being given no answer to give.
    some_short_chain = SOME_CHAIN[:3]

    Scenario() \
        .when(
            lambda: put_in_order(a_model_answering_in_turn(), some_short_chain)
        ) \
        .then(
            the_answer_was(some_short_chain)
        )


@pytest.mark.unit
def test_a_chain_long_enough_is_put_in_the_order_the_model_gives() -> None:
    Scenario() \
        .when(
            lambda: put_in_order(a_model_answering_in_turn({ORDER_FIELD: [1, 3, 2, 4]}),
                                 SOME_CHAIN)
        ) \
        .then(
            the_answer_was([SOME_CHAIN[0], SOME_CHAIN[2], SOME_CHAIN[1], SOME_CHAIN[3]])
        )


@pytest.mark.unit
@pytest.mark.parametrize("failure", [ModelRefused("dont care"), ModelUnavailable("dont care")],
                         ids=["refused", "unavailable-for-now"])
def test_a_model_that_gives_no_order_leaves_the_chain_as_written(failure: Exception) -> None:
    # The write-up is accepted by then; an order is a suggestion about it, and
    # a model that declined to make one, or could not be reached to, is no
    # reason to lose it.
    Scenario() \
        .given(
            a_model_failing := _a_model_failing_with(failure)
        ) \
        .when(
            lambda: put_in_order(a_model_failing, SOME_CHAIN)
        ) \
        .then(
            the_answer_was(SOME_CHAIN)
        )


def _a_model_failing_with(failure: Exception) -> LLMClient:
    class Failing:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int | None = None) -> Turn:
            raise failure

    return Failing()


def _an_order(*numbers: int) -> Turn:
    return a_submission_of({ORDER_FIELD: list(numbers)}, ORDER_TOOL_NAME)


def _says(*expected: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        said = "\n".join(getattr(entry, "text", "") for entry in transcript)
        missing = [wanted for wanted in expected if wanted not in said]
        if missing:
            raise AssertionError(f"Expected the ask to say {missing}, and it said: {said}")

        return True

    return assertion
