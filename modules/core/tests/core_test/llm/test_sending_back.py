"""A submission sent back through its own call's result.

A model that answered with a tool call is answered by that call's result, so an
answer sent back goes there: the model sees what it submitted and why it came
back, in the one shape a provider takes after a call - one result per call,
together. Both write-ups send answers back this way, each in its own words, so
the shape is said once.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.llm import sent_back
from core.models import Ask, ToolCall, ToolResult, ToolResults, Transcript, Turn

SOME_ASK: Transcript = [Ask(text="Write the postmortem.")]
SOME_REASON = "Your postmortem was not accepted: the root cause is missing."
SOME_TOOL = "submit_postmortem"
# Two calls to one tool, told apart by their ids alone.
SOME_CALL_ID = "call-1"
SOME_OTHER_CALL_ID = "call-2"


@pytest.mark.unit
def test_a_submission_is_sent_back_through_its_call_s_result_after_the_conversation_so_far(
) -> None:
    # The conversation, then the turn that submitted, then why it came back:
    # the model sees its own answer before what was wrong with it.
    Scenario() \
        .given(submitted := _a_turn_calling(_a_call_to(SOME_TOOL, SOME_CALL_ID))) \
        .when(lambda: sent_back(SOME_ASK, submitted, SOME_REASON)) \
        .then(the_answer_was([
            *SOME_ASK,
            submitted,
            ToolResults(results=[ToolResult(call_id=SOME_CALL_ID, content=SOME_REASON,
                                            failed=True)])
        ]))


@pytest.mark.unit
def test_every_call_the_turn_made_is_sent_back_together() -> None:
    # A provider expects a result for every call, in one message; a model that
    # submitted twice - the second a placeholder - would otherwise be answered
    # in a conversation the provider will not continue.
    Scenario() \
        .given(submitted := _a_turn_calling(_a_call_to(SOME_TOOL, SOME_CALL_ID),
                                            _a_call_to(SOME_TOOL, SOME_OTHER_CALL_ID))) \
        .when(lambda: sent_back(SOME_ASK, submitted, SOME_REASON)) \
        .then(the_answer_was([
            *SOME_ASK,
            submitted,
            ToolResults(results=[
                ToolResult(call_id=SOME_CALL_ID, content=SOME_REASON, failed=True),
                ToolResult(call_id=SOME_OTHER_CALL_ID, content=SOME_REASON, failed=True)
            ])
        ]))


def _a_call_to(name: str, call_id: str) -> ToolCall:
    dont_care_arguments: dict[str, object] = {}

    return ToolCall(id=call_id, name=name, arguments=dont_care_arguments)


def _a_turn_calling(*calls: ToolCall) -> Turn:
    dont_care_text = ""
    dont_care_tokens = 1

    return Turn(text=dont_care_text, tool_calls=list(calls),
                input_tokens=dont_care_tokens, output_tokens=dont_care_tokens)
