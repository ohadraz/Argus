"""What an agent is told once, rather than at the top of every incident.

An agent's standing instructions - what it is, what its tools are for, what
ends the conversation - do not change between incidents. They were being sent
inside `messages[0]`, glued to the alert and the onset, which cost two things
at once.

The first is cache. Caching is a prefix match rendered `tools` -> `system` ->
`messages`, so the first varying byte decides how much of a request can ever be
read back. With the brief inside the first message, that byte arrived a few
hundred tokens into `messages[0]` and every incident paid full price for text
nobody had edited since it was written. Moved into `system` with a breakpoint
of its own, the prefix up to it is byte-identical for every incident that agent
will ever handle.

The second is authority. A log line the Investigator fetched and a rule it is
judged by were arriving in the same role, and `system` is the channel built for
that difference.

Whether the API *honours* the breakpoint is the third party's half of the
bargain and cannot be checked against a stand-in - that one lives in
`tests/contract/`, where it is paid for. What is checked here is that Argus
asks.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from argus_core.llm.adapters.anthropic_adapter import (
    EPHEMERAL_CACHE,
    AnthropicLLMClient,
)
from argus_core.models.model_policy import (
    LARGEST_UNSTREAMED_ANSWER,
    ModelPolicy,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario, all_of

from argus_core_test.framework.llm import an_api_that_answers, settings_that_reach_no_api

SOME_BRIEF = (
    "You are the Investigator in an autonomous incident-response system. "
    "Find what caused the incident described below."
)


@pytest.mark.unit
def test_an_agents_standing_brief_is_sent_as_its_system_prompt() -> None:
    # Both halves, because either alone passes for the wrong reason: a brief
    # copied into `system` and left in the first message as well would cache
    # nothing and cost more than before, and the request would look right from
    # whichever end the test happened to read.
    some_api = an_api_that_answers()
    investigator = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(brief=SOME_BRIEF),
        client=some_api
    )

    Scenario() \
        .given(
            what_this_incident_is_about := Ask(text="Error rate above threshold")
        ) \
        .when(
            lambda: investigator.converse([what_this_incident_is_about], [_a_tool()])
        ) \
        .then(
            all_of(
                _the_system_prompt_said(some_api, SOME_BRIEF),
                _the_first_message_did_not(some_api, SOME_BRIEF)
            )
        )


@pytest.mark.unit
def test_the_standing_brief_carries_a_breakpoint_of_its_own() -> None:
    # The half that turns a tidy-up into a saving. The top-level breakpoint
    # rides the end of the transcript and so caches nothing between incidents;
    # this one sits on a block that is identical in every incident this agent
    # ever handles, and the prefix up to it includes the tool list.
    some_api = an_api_that_answers()
    investigator = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(brief=SOME_BRIEF),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: investigator.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _the_system_prompt_asked_to_be_cached(some_api)
        )


@pytest.mark.unit
def test_two_incidents_are_told_the_same_thing_to_the_byte() -> None:
    # The property the whole saving rests on, and the one a later edit breaks
    # without noticing: a brief that interpolated anything about the incident
    # would still read correctly, still pass every other test here, and never
    # be read from the cache again.
    some_api = an_api_that_answers()
    investigator = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(brief=SOME_BRIEF),
        client=some_api
    )

    Scenario() \
        .given(
            two_unrelated_incidents := (
                [Ask(text="Error rate above threshold on io-shop")],
                [Ask(text="Memory climbing on checkout, no flag touched")]
            )
        ) \
        .when(
            lambda: [
                investigator.converse(about_one, [_a_tool()])
                for about_one in two_unrelated_incidents
            ]
        ) \
        .then(
            _every_turn_was_told_the_same(some_api)
        )


@pytest.mark.unit
def test_an_agent_with_nothing_standing_to_say_sends_no_system_prompt() -> None:
    # The postmortem's shape. One call per incident, nothing to reuse, and a
    # `system` block carrying an empty string would be a cache breakpoint on
    # nothing - a write premium paid every incident for a prefix no later
    # request can read.
    some_api = an_api_that_answers()
    a_single_shot_agent = AnthropicLLMClient(
        settings_that_reach_no_api(), policy=ModelPolicy(), client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            a_tool := _a_tool()
        ) \
        .when(
            lambda: a_single_shot_agent.converse(dont_care_transcript, [a_tool])
        ) \
        .then(
            _nothing_was_sent_as_a_system_prompt(some_api)
        )


def _the_system_prompt_said(api: Mock, brief: str) -> Assertion[Turn]:
    """That the standing text reached the channel built for it."""
    def assertion(_: Turn) -> bool:
        said = _what_was_sent_as_the_system_prompt(api)

        if not any(block.get("text") == brief for block in said):
            raise AssertionError(
                f"Expected the brief to be sent as the system prompt, and "
                f"[{said}] was sent instead."
            )

        return True

    return assertion


def _the_first_message_did_not(api: Mock, brief: str) -> Assertion[Turn]:
    """That it was moved rather than copied.

    A brief in both places is worse than a brief in neither: the model reads it
    twice, every incident pays for it twice, and the varying first message
    still decides where the cacheable prefix ends.
    """
    def assertion(_: Turn) -> bool:
        first = api.messages.create.call_args.kwargs["messages"][0]

        if brief in str(first):
            raise AssertionError(
                f"Expected the brief to have left the first message, and it "
                f"still carries it: {first}."
            )

        return True

    return assertion


def _the_system_prompt_asked_to_be_cached(api: Mock) -> Assertion[Turn]:
    """That the standing block named a breakpoint, and the right one."""
    def assertion(_: Turn) -> bool:
        said = _what_was_sent_as_the_system_prompt(api)
        marked = [block.get("cache_control") for block in said]

        if EPHEMERAL_CACHE not in marked:
            raise AssertionError(
                f"Expected the system prompt to ask for {EPHEMERAL_CACHE}, and "
                f"its blocks carry {marked}."
            )

        return True

    return assertion


def _every_turn_was_told_the_same(api: Mock) -> Assertion[list[Turn]]:
    """That every call sent one identical system prompt.

    Compared as the whole rendered value rather than field by field, because
    what the cache keys on is the bytes - a block that differed only in its
    `cache_control` would be as much of a miss as one that differed in its
    text.
    """
    def assertion(_: list[Turn]) -> bool:
        each = [call.kwargs.get("system") for call in api.messages.create.call_args_list]

        if len(each) < 2:
            raise AssertionError(
                f"Expected two turns to compare and {len(each)} were taken."
            )

        # Before comparing them, because two turns that sent nothing are
        # identical and prove nothing. The claim is that an agent says the same
        # standing thing every time, which a pair of absences does not make.
        if not all(said for said in each):
            raise AssertionError(
                f"Expected every turn to carry a system prompt to compare, and "
                f"they carried {each}."
            )

        if any(said != each[0] for said in each[1:]):
            raise AssertionError(
                f"Expected every incident to be told the same thing, and they "
                f"were told {each}."
            )

        return True

    return assertion


def _nothing_was_sent_as_a_system_prompt(api: Mock) -> Assertion[Turn]:
    """That an agent with no standing text sends no `system` at all."""
    def assertion(_: Turn) -> bool:
        said = api.messages.create.call_args.kwargs.get("system")

        if said:
            raise AssertionError(
                f"Expected no system prompt from an agent with no brief, and "
                f"[{said}] was sent."
            )

        return True

    return assertion


def _what_was_sent_as_the_system_prompt(api: Mock,
                                       streamed: bool = False) -> list[dict[str, object]]:
    """The system blocks of the turn just taken, or none at all.

    Read as blocks rather than as a string, because the breakpoint is a field
    on a block: a `system` sent as plain text could carry the words and could
    not carry the marker, and the test asserting the words would pass.

    `streamed` picks which way of asking to read, because an agent whose cap
    is above `LARGEST_UNSTREAMED_ANSWER` never touches the other one - and
    Code-Fix, which has the most to gain from the breakpoint, is exactly that
    agent.
    """
    asking = api.messages.stream if streamed else api.messages.create
    said = asking.call_args.kwargs.get("system")

    if not isinstance(said, list):
        raise AssertionError(
            f"Expected the system prompt to be a list of blocks so a "
            f"breakpoint can sit on one, and [{said}] was sent."
        )

    return said


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_logs",
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )


@pytest.mark.unit
def test_an_agent_whose_answers_must_stream_is_told_the_same_thing() -> None:
    # Code-Fix's shape, and the one path the tests above cannot see. Its cap is
    # above `LARGEST_UNSTREAMED_ANSWER`, so every call it makes goes the
    # streamed way and none of them reaches `messages.create` at all.
    #
    # The request is built once and handed to whichever way of asking the room
    # allows, so this holds today by construction. It is asserted anyway,
    # because "by construction" is a property of the code as it stands rather
    # than a promise it keeps: two requests built separately would look right,
    # pass everything above, and quietly cost the agent with the largest tool
    # list its cache.
    some_api = an_api_that_answers()
    code_fix = AnthropicLLMClient(
        settings_that_reach_no_api(),
        policy=ModelPolicy(
            brief=SOME_BRIEF, max_output_tokens=LARGEST_UNSTREAMED_ANSWER + 1
        ),
        client=some_api
    )
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario()         .given(
            a_tool := _a_tool()
        )         .when(
            lambda: code_fix.converse(dont_care_transcript, [a_tool])
        )         .then(
            all_of(
                _the_streamed_request_said(some_api, SOME_BRIEF),
                _the_streamed_request_asked_to_be_cached(some_api)
            )
        )


def _the_streamed_request_said(api: Mock, brief: str) -> Assertion[Turn]:
    """That the standing text reached the streamed way of asking too."""
    def assertion(_: Turn) -> bool:
        said = _what_was_sent_as_the_system_prompt(api, streamed=True)

        if not any(block.get("text") == brief for block in said):
            raise AssertionError(
                f"Expected the streamed request to carry the brief, and "
                f"[{said}] was sent instead."
            )

        return True

    return assertion


def _the_streamed_request_asked_to_be_cached(api: Mock) -> Assertion[Turn]:
    """That the breakpoint travelled with it.

    The half worth having separately: an agent reading a large repository is
    the one whose prefix is most expensive to re-send, so a brief that arrived
    without its marker would cost most exactly where it was meant to save most.
    """
    def assertion(_: Turn) -> bool:
        said = _what_was_sent_as_the_system_prompt(api, streamed=True)
        marked = [block.get("cache_control") for block in said]

        if EPHEMERAL_CACHE not in marked:
            raise AssertionError(
                f"Expected the streamed system prompt to ask for "
                f"{EPHEMERAL_CACHE}, and its blocks carry {marked}."
            )

        return True

    return assertion
