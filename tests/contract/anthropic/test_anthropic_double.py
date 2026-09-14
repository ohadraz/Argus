"""That the double still stands for the API it stands in for.

Two halves, and neither means much alone. One asks the real service whether it
still behaves as Argus's adapter assumes - that a model given tools asks for
one, that the schemas the loop offers are accepted, that a repeated prefix is
served from cache. The other asks whether a body recorded months ago still
parses into the same thing, since every offline suite replays one.

Driven through the SDK rather than through Argus's adapter throughout. The
third party here is Anthropic, and a check routed through Argus's own code
would be checking Argus.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import anthropic
import httpx
import pytest
from agent_investigator.tools import investigator_tools
from anthropic.types import ToolParam
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core import get_settings
from argus_core.llm.adapters.anthropic_adapter import (
    EPHEMERAL_CACHE,
    MAX_TOKENS,
    MODEL,
    TOOL_USE_STOP_REASON,
    TOOL_USE_TYPE,
)
from argus_testkit import Assertion, Scenario, all_of, calling

# These spend real tokens on every run. That is the point - a contract test
# that never talks to the third party is not a contract test - but it is why
# they live behind their own marker and not in `test_all`.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: the real half of the contract cannot be checked"
)

SOME_MODEL_THAT_DOES_NOT_EXIST = "claude-not-a-real-model"

# Enough room for the model to say anything at all. The request is rejected on
# its schema before a token is generated, so what is being paid for here is the
# validation, not the answer.
ENOUGH_TO_SAY_ANYTHING = 8

# Phrased so that answering without the tool is not available: the model is
# asked for something only the log lines contain, over a window it was not
# given. A question it could answer from its own knowledge would make a
# `tool_use` turn the model's preference rather than the API's contract.
SOME_QUESTION_ONLY_THE_TOOL_ANSWERS = (
    "What did the service log between 2026-08-29T22:10:00Z and 2026-08-29T22:20:00Z? "
    "Use the tool to find out; do not guess."
)

# A tool definition minimal enough to be free and specific enough that a model
# given it has an obvious reason to call it. The contract being checked is the
# shape of a tool-use turn, not the model's judgement about when to take one,
# so the question above leaves it no other way to answer.
TOOL_THE_MODEL_MUST_USE_TO_ANSWER: ToolParam = {
    "name": "get_log_lines",
    "description": "Return the service's log lines for a time window.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "window_start": {"type": "string"},
            "window_end": {"type": "string"}
        },
        "required": ["window_start", "window_end"],
        "additionalProperties": False
    }
}


def _recordings_that_stopped_for(reason: str) -> list[str]:
    """The stored recordings whose own `stop_reason` is `reason`.

    The store holds two kinds of answer now, and they are checked differently:
    a verdict is parsed into hypotheses, a tool-use turn is parsed into the
    calls it requests. Which kind a file is, is not a naming convention to be
    maintained by hand - it is written in the recording, so it is read from
    there and cannot drift out of step with the file it describes.

    Read at collection time, like `recordings.available()` already is. A
    recording that fails to load is a broken store and should fail loudly
    during collection rather than as a puzzling parametrize of nothing.
    """
    return [
        name
        for name in recordings.available()
        if recordings.load(name).get("stop_reason") == reason
    ]


@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.contract
@needs_the_real_api
def test_the_real_api_still_answers_a_tool_call_with_a_tool_use_turn() -> None:
    # The second thing Argus asks of the API, and the one the Investigator's
    # loop is built on: given tools and a question it cannot answer without
    # them, the model asks for one. What is asserted is the turn's shape -
    # the stop reason that means "I am not finished", and a block carrying the
    # tool's name and an input that parses - because that shape is what the
    # loop dispatches on. Which window it asks for is judgement, measured by
    # the eval suite, and asserting it here would fail for the one reason that
    # is not a contract break.
    Scenario() \
        .given(
            real := anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        ) \
        .when(
            lambda: real.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=[TOOL_THE_MODEL_MUST_USE_TO_ANSWER],
                messages=[{"role": "user", "content": SOME_QUESTION_ONLY_THE_TOOL_ANSWERS}]
            )
        ) \
        .then(all_of(
            _the_turn_stopped_for(TOOL_USE_STOP_REASON),
            _a_tool_was_asked_for(),
            _every_tool_asked_for_was("get_log_lines"),
            _every_tool_call_carried_an_input()
        ))


@pytest.mark.contract
@needs_the_real_api
def test_the_real_api_accepts_every_tool_the_investigator_offers() -> None:
    # The one thing about a tool offer that nothing offline can check. The
    # double never inspects a request, so it accepts any schema at all, and
    # `e2e_replay` serves an answer without one having been validated - which
    # means a schema the API rejects passes every free suite and fails only
    # when a real incident is investigated.
    #
    # What is offered is what the loop offers, rendered by the same `to_wire`
    # the adapter sends, because a schema written out by hand here would only
    # be checking this test's idea of the offer. The only assertion is that a
    # turn came back at all: the contract being checked is that the request was
    # accepted, and a rejection arrives as `BadRequestError` naming the tool and
    # the field, which is a better failure than any assertion could word.
    Scenario() \
        .given(
            real := anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
        ) \
        .when(
            lambda: real.messages.create(
                model=MODEL,
                max_tokens=ENOUGH_TO_SAY_ANYTHING,
                tools=[cast(ToolParam, tool.to_wire()) for tool in investigator_tools()],
                messages=[{"role": "user", "content": "hi"}]
            )
        ) \
        .then(
            _the_request_was_accepted()
        )


@pytest.mark.contract
@needs_the_real_api
def test_the_real_api_still_serves_a_repeated_prefix_from_cache() -> None:
    # The other thing about a request that nothing offline can check. The
    # double neither reads a request nor reports usage, so a breakpoint that
    # the API silently ignores - a prefix under the model's minimum, a
    # parameter the SDK stopped sending - passes every free suite and shows up
    # only as a bill.
    #
    # Two identical requests, because that is the whole claim: the first pays
    # the write premium, the second reads what it wrote. What is offered is
    # what the loop offers, so the prefix under test is the real one - and it
    # is the tool schemas that carry it past the model's minimum cacheable
    # size, which is why they are here rather than a shorter stand-in.
    real = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    offered = [cast(ToolParam, tool.to_wire()) for tool in investigator_tools()]
    # A prefix no earlier run can already have cached. Both calls below share
    # it, so the claim is unchanged - but a second run of this suite inside the
    # cache's lifetime would otherwise find the prefix warm, read where it
    # meant to write, and fail as though the API had stopped caching.
    asked_only_this_run = f"{SOME_QUESTION_ONLY_THE_TOOL_ANSWERS} (run {uuid4().hex})"

    def ask() -> anthropic.types.Message:
        return real.messages.create(
            model=MODEL,
            max_tokens=ENOUGH_TO_SAY_ANYTHING,
            cache_control=EPHEMERAL_CACHE,
            tools=offered,
            messages=[{"role": "user", "content": asked_only_this_run}]
        )

    Scenario() \
        .given(
            asked_only_this_run
        ) \
        .when(
            lambda: [ask(), ask()]
        ) \
        .then(
            _the_prefix_was_written_then_read()
        )


@pytest.mark.contract
@pytest.mark.parametrize("recording", _recordings_that_stopped_for(TOOL_USE_STOP_REASON))
def test_a_stored_tool_use_recording_still_parses_as_a_tool_use_turn(
    double: httpx.Client, recording: str
) -> None:
    # The same staleness check for the other kind of answer, and it is needed
    # for the same reason: a tool-use recording is what the Investigator's loop
    # replays, and a body the SDK can no longer parse into tool calls would
    # leave every replayed investigation reading nothing while the suite stayed
    # green.
    replaying = anthropic.Anthropic(api_key="not-used", base_url=DEFAULT_BASE_URL)

    Scenario() \
        .given(
            calling(lambda: double.post("/double-control/seed", json={"recording": recording}))
        ) \
        .when(
            lambda: replaying.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                tools=[TOOL_THE_MODEL_MUST_USE_TO_ANSWER],
                messages=[{"role": "user", "content": SOME_QUESTION_ONLY_THE_TOOL_ANSWERS}]
            )
        ) \
        .then(all_of(
            _the_turn_stopped_for(TOOL_USE_STOP_REASON),
            _a_tool_was_asked_for(),
            _every_tool_call_carried_an_id(),
            _every_tool_call_carried_an_input()
        ))


@pytest.mark.contract
@needs_the_real_api
def test_a_rejected_request_raises_the_same_error_class_from_both(
    double: httpx.Client
) -> None:
    # Not the same *request* - the double never inspects one, so it cannot
    # reject a bad model on its own. What is compared is the rejection: given
    # an equivalent refusal, does the SDK raise the same class? That is what
    # a test seeding a status on the double is entitled to assume.
    real = anthropic.Anthropic(api_key=get_settings().anthropic_api_key, max_retries=0)
    replaying = anthropic.Anthropic(
        api_key="not-used", base_url=DEFAULT_BASE_URL, max_retries=0
    )

    Scenario() \
        .given(
            calling(lambda: double.post("/double-control/seed", json={"status": 404}))
        ) \
        .when(
            lambda: [
                _the_error_from(real, model=SOME_MODEL_THAT_DOES_NOT_EXIST),
                _the_error_from(replaying, model=MODEL)
            ]
        ) \
        .then(
            _both_refusals_were_the_same_class()
        )


def _the_turn_stopped_for(reason: str) -> Assertion[anthropic.types.Message]:
    def assertion(answer: anthropic.types.Message) -> bool:
        if answer.stop_reason != reason:
            raise AssertionError(f"Expected [{reason}], got [{answer.stop_reason}].")

        return True

    return assertion


def _a_tool_was_asked_for() -> Assertion[anthropic.types.Message]:
    def assertion(answer: anthropic.types.Message) -> bool:
        if not _the_tool_calls_in(answer):
            raise AssertionError(
                f"Expected at least one tool call, the turn carried "
                f"{[block.type for block in answer.content]}."
            )

        return True

    return assertion


def _every_tool_asked_for_was(name: str) -> Assertion[anthropic.types.Message]:
    def assertion(answer: anthropic.types.Message) -> bool:
        named = [call.name for call in _the_tool_calls_in(answer)]

        if any(called != name for called in named):
            raise AssertionError(f"Expected every call to be [{name}], got {named}.")

        return True

    return assertion


def _every_tool_call_carried_an_id() -> Assertion[anthropic.types.Message]:
    """That each call can be answered.

    A result is returned against the id of the call it answers, so a block
    without one is a call the loop cannot reply to - and the conversation stops
    there rather than anywhere a reader would look.
    """
    def assertion(answer: anthropic.types.Message) -> bool:
        unanswerable = [call.name for call in _the_tool_calls_in(answer) if not call.id]

        if unanswerable:
            raise AssertionError(f"Expected every call to carry an id, {unanswerable} did not.")

        return True

    return assertion


def _every_tool_call_carried_an_input() -> Assertion[anthropic.types.Message]:
    def assertion(answer: anthropic.types.Message) -> bool:
        unparsed = [
            call.name for call in _the_tool_calls_in(answer) if not isinstance(call.input, dict)
        ]

        if unparsed:
            raise AssertionError(f"Expected every input to parse, {unparsed} did not.")

        return True

    return assertion


def _the_request_was_accepted() -> Assertion[anthropic.types.Message]:
    """That a turn came back at all.

    The whole claim: a rejected schema arrives as a `BadRequestError` naming
    the tool and the field, which says more than any assertion here could.
    """
    def assertion(answer: anthropic.types.Message) -> bool:
        if answer.stop_reason is None:
            raise AssertionError("Expected a finished turn, got one with no stop reason.")

        return True

    return assertion


def _the_prefix_was_written_then_read() -> Assertion[list[anthropic.types.Message]]:
    def assertion(asked_twice: list[anthropic.types.Message]) -> bool:
        wrote, read = asked_twice

        if not wrote.usage.cache_creation_input_tokens:
            raise AssertionError(
                f"Expected the first request to write the prefix to cache, its usage was "
                f"{wrote.usage}."
            )

        if not read.usage.cache_read_input_tokens:
            raise AssertionError(
                f"Expected the second request to read it back, its usage was {read.usage}."
            )

        return True

    return assertion


def _both_refusals_were_the_same_class() -> Assertion[list[Exception]]:
    def assertion(refusals: list[Exception]) -> bool:
        from_the_real_api, from_the_double = refusals

        if type(from_the_double) is not type(from_the_real_api):
            raise AssertionError(
                f"Expected the double to raise [{type(from_the_real_api).__name__}], "
                f"got [{type(from_the_double).__name__}]."
            )

        return True

    return assertion


def _the_error_from(client: anthropic.Anthropic, model: str) -> Exception:
    try:
        client.messages.create(
            model=model, max_tokens=8, messages=[{"role": "user", "content": "hi"}]
        )
    except Exception as error:
        return error

    raise AssertionError(f"expected {model} to be rejected, but the call succeeded")


def _the_tool_calls_in(answer: anthropic.types.Message) -> list[anthropic.types.ToolUseBlock]:
    """The tool-use blocks of one turn, which is what a loop dispatches on.

    A turn carries thinking and text blocks alongside them, so the calls are
    selected by type rather than by position - and a model may ask for several
    tools in one turn, which is why this is a list and not the first match.
    """
    return [block for block in answer.content if block.type == TOOL_USE_TYPE]
