from __future__ import annotations

from typing import Any, Final

import pytest
from argus_core.llm.adapters.anthropic_adapter import to_messages
from argus_core.models.transcript import Ask, ToolResult, ToolResults, Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Scenario, all_of

"""How a conversation Argus is holding becomes the request the API expects.

`Turn` covers one reply coming back and `ToolDefinition` covers the tools
going out; this covers the third thing on that boundary - the record of what
has been asked and answered so far, which every turn resends in full because
the API keeps no state.

The transcript is Argus's own - an `Ask`, the `Turn`s that answered it, and the
`ToolResults` that answered those - and only this translation knows what any of
it looks like on the wire. That is the whole point of the type: a loop that
appended vendor-shaped dictionaries would put Anthropic one module further up
than the adapter, and the next provider would be a rewrite of the loop rather
than of the adapter.
"""


# Anthropic's own vocabulary for a request's messages. Stated here rather than
# imported from the code under test: a test that borrowed Argus's spelling
# would agree with it even when both are wrong.
ROLE_KEY: Final = "role"
CONTENT_KEY: Final = "content"

USER_ROLE: Final = "user"
ASSISTANT_ROLE: Final = "assistant"

TYPE_KEY: Final = "type"
TOOL_RESULT_TYPE: Final = "tool_result"
TOOL_USE_ID_KEY: Final = "tool_use_id"
IS_ERROR_KEY: Final = "is_error"


@pytest.mark.unit
def test_what_argus_asked_is_a_message_from_the_user() -> None:
    # The opening message, and the only thing in a transcript Argus writes as
    # prose. Everything after it is a record of what the model did and what it
    # got back.
    some_question = "HighErrorRate on io-shop. The onset is 2026-08-29T22:15:00Z."

    Scenario() \
        .given(
            some_transcript := [Ask(text=some_question)]
        ) \
        .when(
            lambda: to_messages(some_transcript)
        ) \
        .then(
            all_of(
                _the_messages_are_from([USER_ROLE]),
                _the_message_at(0, carries=some_question)
            )
        )


@pytest.mark.unit
def test_the_results_of_one_turn_go_back_as_a_single_message() -> None:
    # The rule this type exists to make unbreakable. A model may ask for
    # several tools in one turn, and the API expects every result in one user
    # message; splitting them across messages is accepted and quietly teaches
    # the model to stop asking for tools in parallel - a regression nothing
    # fails on and nobody sees.
    #
    # `ToolResults` holds them together for exactly that reason: the grouping
    # is a property of the type rather than a discipline the loop has to keep.
    some_call_id = "toolu_1"
    another_call_id = "toolu_2"
    dont_care_lines = "2026-08-29T22:15:00Z ERROR io-shop: boom"

    Scenario() \
        .given(
            some_transcript := [
                ToolResults(results=[
                    ToolResult(call_id=some_call_id, content=dont_care_lines),
                    ToolResult(call_id=another_call_id, content=dont_care_lines)
                ])
            ]
        ) \
        .when(
            lambda: to_messages(some_transcript)
        ) \
        .then(
            all_of(
                _the_messages_are_from([USER_ROLE]),
                _the_results_answer([some_call_id, another_call_id])
            )
        )


@pytest.mark.unit
def test_a_result_that_failed_is_marked_as_an_error() -> None:
    # A tool that could not be served still has to answer the call it was
    # made for - an unanswered request leaves the model waiting - so the
    # failure travels as a result rather than as a missing one. The flag is
    # what tells the model this is something to recover from rather than
    # evidence about the incident.
    some_call_id = "toolu_1"
    some_complaint = "the window ends before it starts"

    Scenario() \
        .given(
            some_transcript := [
                ToolResults(results=[
                    ToolResult(call_id=some_call_id, content=some_complaint, failed=True)
                ])
            ]
        ) \
        .when(
            lambda: to_messages(some_transcript)
        ) \
        .then(
            _the_result_for(some_call_id, failed=True)
        )


@pytest.mark.unit
def test_a_result_that_was_served_is_not_marked_as_an_error() -> None:
    # The other side of the same flag, and the one that matters more: a
    # translation that marked everything would have the model treating every
    # log window it retrieved as a failure to recover from.
    some_call_id = "toolu_1"
    dont_care_lines = "2026-08-29T22:15:00Z ERROR io-shop: boom"

    Scenario() \
        .given(
            some_transcript := [
                ToolResults(results=[
                    ToolResult(call_id=some_call_id, content=dont_care_lines)
                ])
            ]
        ) \
        .when(
            lambda: to_messages(some_transcript)
        ) \
        .then(
            _the_result_for(some_call_id, failed=False)
        )


@pytest.mark.unit
def test_an_exchange_reaches_the_model_in_the_order_it_happened() -> None:
    # A transcript is a sequence, and the model reads it as one. Reordering it
    # - or dropping the turn between an ask and its results - would leave tool
    # results answering a request the model cannot see it made.
    dont_care_question = "dont care what was asked"
    dont_care_lines = "dont care what came back"
    dont_care_call_id = "toolu_1"
    some_transcript: Transcript = [
        Ask(text=dont_care_question),
        _a_turn_that_asked_for(dont_care_call_id),
        ToolResults(results=[
            ToolResult(call_id=dont_care_call_id, content=dont_care_lines)
        ])
    ]

    Scenario() \
        .given(
            some_transcript
        ) \
        .when(
            lambda: to_messages(some_transcript)
        ) \
        .then(
            _the_messages_are_from([USER_ROLE, ASSISTANT_ROLE, USER_ROLE])
        )


def _the_messages_are_from(roles: list[str]) -> Assertion[list[dict[str, Any]]]:
    """Who each message is attributed to, in order - and how many there are."""
    def assertion(messages: list[dict[str, Any]]) -> bool:
        spoken_by = [message.get(ROLE_KEY) for message in messages]
        if spoken_by != roles:
            raise AssertionError(f"Expected messages from {roles}, got {spoken_by}.")

        return True

    return assertion


def _the_message_at(position: int, carries: str) -> Assertion[list[dict[str, Any]]]:
    """What one message says, for the one entry that is prose."""
    def assertion(messages: list[dict[str, Any]]) -> bool:
        content = messages[position].get(CONTENT_KEY)
        if content != carries:
            raise AssertionError(
                f"Expected message {position} to carry [{carries}], got [{content}]."
            )

        return True

    return assertion


def _the_results_answer(call_ids: list[str]) -> Assertion[list[dict[str, Any]]]:
    """The calls one message's results are labelled as answering."""
    def assertion(messages: list[dict[str, Any]]) -> bool:
        answered = [
            block.get(TOOL_USE_ID_KEY)
            for message in messages
            for block in _the_result_blocks_of(message)
        ]
        if answered != call_ids:
            raise AssertionError(f"Expected results answering {call_ids}, got {answered}.")

        return True

    return assertion


def _the_result_for(call_id: str, failed: bool) -> Assertion[list[dict[str, Any]]]:
    """Whether one result is offered as a failure to recover from."""
    def assertion(messages: list[dict[str, Any]]) -> bool:
        for message in messages:
            for block in _the_result_blocks_of(message):
                if block.get(TOOL_USE_ID_KEY) != call_id:
                    continue

                if bool(block.get(IS_ERROR_KEY, False)) != failed:
                    raise AssertionError(
                        f"Expected the result for [{call_id}] to report failed="
                        f"[{failed}], got [{block.get(IS_ERROR_KEY)}]."
                    )

                return True

        raise AssertionError(f"No result answering [{call_id}] was sent at all.")

    return assertion


def _the_result_blocks_of(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get(CONTENT_KEY)
    if not isinstance(content, list):
        return []

    return [block for block in content if block.get(TYPE_KEY) == TOOL_RESULT_TYPE]


def _a_turn_that_asked_for(call_id: str) -> Turn:
    dont_care_what_it_said = "dont care what it said"
    dont_care_tokens = 1

    return Turn(
        text=dont_care_what_it_said,
        tool_calls=[ToolCall(id=call_id, name="get_logs", arguments={})],
        input_tokens=dont_care_tokens,
        output_tokens=dont_care_tokens
    )
