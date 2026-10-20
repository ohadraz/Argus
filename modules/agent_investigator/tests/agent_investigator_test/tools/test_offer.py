"""What the Investigator is given, taken as a whole.

The tier boundary lives here rather than in a prompt: the Investigator is
read-only because of what it possesses, so what it possesses is asserted
rather than assumed. Each channel's own behaviour is tested beside the channel;
this file is only about the offer.

Three of its reads are the read tier's, which serves Code-Fix's reads as well -
so what the Investigator holds there is named here, and what each of them says
to a model is the server's to declare.
"""

from __future__ import annotations

import pytest
from agent_investigator.tools import (
    ANSWER_TOOL,
    CHANGES_TOOL,
    DEPENDENCIES_TOOL,
    DEPLOYMENT_DIFF_TOOL,
    LOGS_TOOL,
    METRICS_TOOL,
    ROLLOUT_TOOL,
    investigator_tools,
)
from agent_investigator.tools.offer import READ_TIER_HELD
from argus_core.models import ToolDefinition
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVED_TOOLS = [
    ToolDefinition(name="some_read",
                   description="dont care what it reads",
                   properties={"revision": {"type": "string"}},
                   required=["revision"]),
    ToolDefinition(name="another_read",
                   description="dont care what it reads",
                   properties={},
                   required=[])
]


@pytest.mark.unit
def test_the_investigator_holds_three_reads_of_the_read_tier_and_fills_in_the_service() -> None:
    # Argus is allowed to act on production, and the thing that keeps
    # investigation from doing so is which tools it holds - so a write tool
    # appearing in this list is the failure that matters most in this package.
    # The service is the incident's, never the model's to name.
    Scenario() \
        .when(lambda: READ_TIER_HELD) \
        .then(_the_holding_is({
            DEPENDENCIES_TOOL: {"service"},
            DEPLOYMENT_DIFF_TOOL: {"service"},
            ROLLOUT_TOOL: {"service"}
        }))


@pytest.mark.unit
def test_the_investigator_offers_its_own_tools_around_what_the_read_tier_serves() -> None:
    # The order is the prompt: the windowed reads first, the read tier's in the
    # order it served them, and the way to finish last.
    Scenario() \
        .when(lambda: investigator_tools(SOME_SERVED_TOOLS)) \
        .then(all_of(
            _the_tools_offered_are([
                METRICS_TOOL, LOGS_TOOL, CHANGES_TOOL,
                *(tool.name for tool in SOME_SERVED_TOOLS),
                ANSWER_TOOL
            ]),
            _every_tool_is_offered_strictly()
        ))


def _the_holding_is(expected: dict[str, set[str]]) -> Assertion[object]:
    """Exactly the tools held, each with the arguments its caller fills in."""
    def assertion(held: object) -> bool:
        if held != expected:
            raise AssertionError(f"Expected the read tier held as {expected}, got {held}.")

        return True

    return assertion


def _the_tools_offered_are(names: list[str]) -> Assertion[list[ToolDefinition]]:
    """Exactly the offered tools, in the order offered."""
    def assertion(tools: list[ToolDefinition]) -> bool:
        offered = [tool.name for tool in tools]
        if offered != names:
            raise AssertionError(f"Expected the tools {names}, got {offered}.")

        return True

    return assertion


def _every_tool_is_offered_strictly() -> Assertion[list[ToolDefinition]]:
    """No tool may accept an argument the dispatcher was not written for."""
    def assertion(tools: list[ToolDefinition]) -> bool:
        loose = [tool.name for tool in tools if tool.to_wire().get("strict") is not True]
        if loose:
            raise AssertionError(f"Expected every tool to be strict, but {loose} were not.")

        return True

    return assertion
