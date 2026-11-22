"""Anthropic, as the provider a process's wiring hands out.

What the port asks of a provider is two things - a name telemetry calls it by,
and a client per policy - and what this file pins is that the second is built
the way the factory always built one: under the policy it was asked for, over
the SDK client it was handed where a test hands one. The client's own
behaviour is the rest of this directory's.
"""

from __future__ import annotations

from typing import Final
from unittest.mock import Mock

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core.models import Ask, ModelPolicy, Reasoning, ToolDefinition, Turn
from llm_anthropic import EFFORT_ON_THE_WIRE, AnthropicProvider

from llm_anthropic_test.framework.llm import an_api_that_answers, settings_that_reach_no_api

# How OTel's GenAI conventions spell Anthropic in `gen_ai.provider.name`, stated
# here rather than imported from the adapter that declares it, for the reason
# the field names below are.
OTEL_S_NAME_FOR_ANTHROPIC: Final = "anthropic"

# Anthropic's names for the request's fields this file reads, stated here rather
# than imported: a test borrowing the adapter's spelling would agree with it
# even where both were wrong.
MODEL_FIELD: Final = "model"
OUTPUT_CONFIG_FIELD: Final = "output_config"
EFFORT_FIELD: Final = "effort"


@pytest.mark.unit
def test_the_provider_is_named_as_telemetry_names_anthropic() -> None:
    # The span every call is timed under names who answered. A provider that
    # named itself anything else would split one vendor's calls across two
    # names on every dashboard that groups by it.
    Scenario() \
        .when(
            lambda: AnthropicProvider(settings_that_reach_no_api()).name
        ) \
        .then(
            the_answer_was(OTEL_S_NAME_FOR_ANTHROPIC)
        )


@pytest.mark.unit
def test_a_client_the_provider_builds_asks_under_the_policy_it_was_given() -> None:
    # One provider serves every agent of a process, and each agent asks for its
    # own model and effort. A client built under any policy but the one asked
    # for would answer as the wrong agent, in the right shape.
    some_api = an_api_that_answers()
    some_policy = ModelPolicy(model="claude-haiku-4-5", effort=Reasoning.HIGHER)
    a_provider = AnthropicProvider(settings_that_reach_no_api(), sdk=some_api)
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .when(
            lambda: a_provider.client(some_policy).converse(dont_care_transcript, [_a_tool()])
        ) \
        .then(
            all_of(
                _the_request_named(some_api, MODEL_FIELD, some_policy.model),
                _the_request_named(some_api, OUTPUT_CONFIG_FIELD,
                                   {EFFORT_FIELD: EFFORT_ON_THE_WIRE[some_policy.effort]})
            )
        )


@pytest.mark.unit
def test_two_providers_reached_the_same_way_are_the_same_provider() -> None:
    # A value, so a binding can be read for which provider it was given - the
    # judge's at its own address, the agents' at theirs - without a client
    # ever being built to find out.
    Scenario() \
        .given(
            a_provider := AnthropicProvider(settings_that_reach_no_api())
        ) \
        .when(
            lambda: a_provider == AnthropicProvider(settings_that_reach_no_api())
        ) \
        .then(
            the_answer_was(True)
        )


def _the_request_named(api: Mock, field: str, expected: object) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        asked = api.messages.create.call_args.kwargs.get(field)

        if asked != expected:
            raise AssertionError(f"Expected the request's [{field}] to be [{expected}], "
                                 f"got [{asked}].")

        return True

    return assertion


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="get_logs",
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )
