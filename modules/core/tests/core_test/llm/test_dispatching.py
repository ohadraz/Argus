"""A tool call served by the handler its tool's name picks.

Both agents served the model's calls through a chain of name checks, each
ending in words of its own for a tool that does not exist. What a handler does
and what an unknown tool is told are the agent's; picking the handler by name
is said once here.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from core.llm import served_by_name
from core.models import ToolCall

SOME_TOOL = "read_logs"
SOME_OTHER_TOOL = "read_metrics"
A_TOOL_NOBODY_SERVES = "read_the_future"
SOME_ANSWER = "3 log lines"
SOME_OTHER_ANSWER = "12 minutes of metrics"
NO_SUCH_TOOL = "there is no such tool"
DONT_CARE_REASON = "dont care"


@pytest.mark.unit
def test_a_call_is_served_by_the_handler_its_tool_names_and_no_other() -> None:
    served: Kept[ToolCall] = Kept()
    not_served: Kept[ToolCall] = Kept()

    Scenario() \
        .given(some_call := _a_call_to(SOME_TOOL)) \
        .when(lambda: served_by_name(
            some_call,
            {SOME_TOOL: _answering(SOME_ANSWER, served),
             SOME_OTHER_TOOL: _answering(SOME_OTHER_ANSWER, not_served)},
            unknown=_answering(NO_SUCH_TOOL, not_served))) \
        .then(all_of(the_answer_was(SOME_ANSWER),
                     _handed(served, [some_call]),
                     _handed(not_served, [])))


@pytest.mark.unit
def test_a_call_to_a_tool_no_handler_serves_is_told_what_the_agent_says_of_one() -> None:
    unknown: Kept[ToolCall] = Kept()
    not_served: Kept[ToolCall] = Kept()

    Scenario() \
        .given(some_call := _a_call_to(A_TOOL_NOBODY_SERVES)) \
        .when(lambda: served_by_name(
            some_call,
            {SOME_TOOL: _answering(SOME_ANSWER, not_served)},
            unknown=_answering(NO_SUCH_TOOL, unknown))) \
        .then(all_of(the_answer_was(NO_SUCH_TOOL),
                     _handed(unknown, [some_call]),
                     _handed(not_served, [])))


@pytest.mark.unit
def test_what_a_handler_raises_reaches_the_caller_as_it_was_raised() -> None:
    # Code-Fix tells the model what failed, by the error's own type and words:
    # caught or remade here, it would be told something else.
    some_failure = RuntimeError(DONT_CARE_REASON)

    Scenario() \
        .given(some_call := _a_call_to(SOME_TOOL)) \
        .when(attempting(lambda: served_by_name(
            some_call,
            {SOME_TOOL: _raising(some_failure)},
            unknown=_answering(NO_SUCH_TOOL, Kept())))) \
        .then(the_same_error_reached_the_caller(some_failure))


def _raising(failure: Exception) -> Callable[[ToolCall], str]:
    def handler(call: ToolCall) -> str:
        raise failure

    return handler


def _a_call_to(name: str) -> ToolCall:
    dont_care_call_id = "dont-care-call-id"
    dont_care_arguments: dict[str, object] = {}

    return ToolCall(id=dont_care_call_id, name=name, arguments=dont_care_arguments)


def _answering(answer: str, handed: Kept[ToolCall]) -> Callable[[ToolCall], str]:
    """A handler that keeps the call it was handed and answers `answer`."""
    def handler(call: ToolCall) -> str:
        handed.take(call)
        return answer

    return handler


def _handed(kept: Kept[ToolCall], expected: list[ToolCall]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if kept.taken != expected:
            raise AssertionError(f"Expected the handler handed {expected}, got {kept.taken}.")

        return True

    return assertion
