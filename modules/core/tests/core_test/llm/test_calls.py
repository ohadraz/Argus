"""The calls a turn made to one tool, found by the tool's name.

Every loop that drives a model reads its turn the same way: did it call the
tool that answers, and with what. Each used to spell that lookup itself, and
the spellings had already parted - some answered "none" where the call was
missing, others raised StopIteration out of a generator. One lookup, said once.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.llm import the_call, the_calls
from core.models import ToolCall, Turn

SOME_TOOL = "submit_answer"
SOME_OTHER_TOOL = "read_logs"
# Two calls to one tool, told apart by their ids alone.
SOME_CALL_ID = "call-1"
SOME_OTHER_CALL_ID = "call-2"


@pytest.mark.unit
def test_a_call_to_a_tool_is_found_by_the_tool_s_name() -> None:
    # Among calls to other tools, since a turn that answers often reads in the
    # same breath, and a lookup that took the first call would hand back a read.
    Scenario() \
        .given(turn := _a_turn_calling(_a_call_to(SOME_OTHER_TOOL),
                                       answering := _a_call_to(SOME_TOOL))) \
        .when(lambda: the_call(turn, SOME_TOOL)) \
        .then(the_answer_was(answering))


@pytest.mark.unit
def test_of_two_calls_to_a_tool_the_first_is_the_one_found() -> None:
    # The order every caller read in before: the first the model made.
    Scenario() \
        .given(turn := _a_turn_calling(first := _a_call_to(SOME_TOOL, SOME_CALL_ID),
                                       _a_call_to(SOME_TOOL, SOME_OTHER_CALL_ID))) \
        .when(lambda: the_call(turn, SOME_TOOL)) \
        .then(the_answer_was(first))


@pytest.mark.unit
def test_a_turn_that_never_called_a_tool_has_no_call_to_it() -> None:
    Scenario() \
        .given(turn := _a_turn_calling(_a_call_to(SOME_OTHER_TOOL))) \
        .when(lambda: the_call(turn, SOME_TOOL)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_every_call_to_a_tool_is_found_in_the_order_it_was_made() -> None:
    # And none of the calls to other tools between them.
    Scenario() \
        .given(turn := _a_turn_calling(first := _a_call_to(SOME_TOOL, SOME_CALL_ID),
                                       _a_call_to(SOME_OTHER_TOOL),
                                       second := _a_call_to(SOME_TOOL, SOME_OTHER_CALL_ID))) \
        .when(lambda: the_calls(turn, SOME_TOOL)) \
        .then(the_answer_was([first, second]))


@pytest.mark.unit
def test_a_turn_that_never_called_a_tool_has_no_calls_to_it() -> None:
    Scenario() \
        .given(turn := _a_turn_calling(_a_call_to(SOME_OTHER_TOOL))) \
        .when(lambda: the_calls(turn, SOME_TOOL)) \
        .then(the_answer_was([]))


def _a_call_to(name: str, call_id: str = "dont-care-call-id") -> ToolCall:
    dont_care_arguments: dict[str, object] = {}

    return ToolCall(id=call_id, name=name, arguments=dont_care_arguments)


def _a_turn_calling(*calls: ToolCall) -> Turn:
    dont_care_text = ""
    dont_care_tokens = 1

    return Turn(text=dont_care_text, tool_calls=list(calls),
                input_tokens=dont_care_tokens, output_tokens=dont_care_tokens)
