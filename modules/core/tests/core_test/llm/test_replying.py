"""What a model driving a loop is told before its next turn.

The results of what it asked for, with anything due riding on the last of them
- news from the thread, a warning that this is its last turn - since that is
the condition the whole reply is to be read under, not a thing apart. A turn
that asked for nothing still has to be answered, or the conversation holds two
turns from the model in a row; the agent says in words of its own what such a
turn is told, and the postscript rides on that instead.

Both agents said this in their own copy. The words are theirs; the shape is
said once here.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.llm import told_next
from core.models import Ask, ToolResult, ToolResults

SOME_POSTSCRIPT = "\n\nThis is your last turn."
SOME_REMARK = "That turn asked for nothing."
SOME_CALL_ID = "call-1"
SOME_OTHER_CALL_ID = "call-2"
SOME_CONTENT = "3 log lines"
SOME_OTHER_CONTENT = "no deploys"
NO_POSTSCRIPT = ""


@pytest.mark.unit
def test_the_postscript_rides_on_the_last_result_and_the_others_are_as_they_came() -> None:
    Scenario() \
        .given(results := [ToolResult(call_id=SOME_CALL_ID, content=SOME_CONTENT),
                           ToolResult(call_id=SOME_OTHER_CALL_ID, content=SOME_OTHER_CONTENT)]) \
        .when(lambda: told_next(results, SOME_POSTSCRIPT, nothing_asked=SOME_REMARK)) \
        .then(the_answer_was(ToolResults(results=[
            ToolResult(call_id=SOME_CALL_ID, content=SOME_CONTENT),
            ToolResult(call_id=SOME_OTHER_CALL_ID,
                       content=SOME_OTHER_CONTENT + SOME_POSTSCRIPT)
        ])))


@pytest.mark.unit
@pytest.mark.parametrize("failed", [True, False], ids=["failed", "answered"])
def test_the_last_result_keeps_whether_it_failed(failed: bool) -> None:
    # A failed result says "fix this" and an answered one "this is what came
    # back"; a postscript riding on it says neither.
    Scenario() \
        .given(results := [ToolResult(call_id=SOME_CALL_ID, content=SOME_CONTENT,
                                      failed=failed)]) \
        .when(lambda: told_next(results, SOME_POSTSCRIPT, nothing_asked=SOME_REMARK)) \
        .then(the_answer_was(ToolResults(results=[
            ToolResult(call_id=SOME_CALL_ID, content=SOME_CONTENT + SOME_POSTSCRIPT,
                       failed=failed)
        ])))


@pytest.mark.unit
def test_with_nothing_due_the_results_are_told_as_they_came() -> None:
    Scenario() \
        .given(results := [ToolResult(call_id=SOME_CALL_ID, content=SOME_CONTENT)]) \
        .when(lambda: told_next(results, NO_POSTSCRIPT, nothing_asked=SOME_REMARK)) \
        .then(the_answer_was(ToolResults(results=results)))


@pytest.mark.unit
def test_a_turn_that_asked_for_nothing_is_told_the_remark_with_the_postscript_on_it() -> None:
    # Dropped there, news would be counted as shown and never sent.
    Scenario() \
        .when(lambda: told_next([], SOME_POSTSCRIPT, nothing_asked=SOME_REMARK)) \
        .then(the_answer_was(Ask(text=SOME_REMARK + SOME_POSTSCRIPT)))
