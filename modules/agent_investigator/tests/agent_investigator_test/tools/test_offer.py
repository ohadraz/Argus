from __future__ import annotations

import pytest
from agent_investigator.tools import (
    ANSWER_TOOL,
    CHANGES_TOOL,
    LOGS_TOOL,
    METRICS_TOOL,
    investigator_tools,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_testkit import Assertion, Scenario, all_of

"""What the Investigator is given, taken as a whole.

The tier boundary lives here rather than in a prompt: the Investigator is
read-only because of what it possesses, so what it possesses is asserted
rather than assumed. Each channel's own behaviour is tested beside the channel;
this file is only about the offer.
"""


@pytest.mark.unit
def test_the_investigator_is_offered_nothing_that_changes_anything() -> None:
    # Argus is allowed to act on production, and the thing that keeps
    # investigation from doing so is which tools it holds - so a write tool
    # appearing in this list is the failure that matters most in this package.
    read_only_names = {LOGS_TOOL, METRICS_TOOL, CHANGES_TOOL, ANSWER_TOOL}

    Scenario() \
        .when(
            lambda: investigator_tools()
        ) \
        .then(
            all_of(
                _every_tool_is_named_in(read_only_names),
                _every_tool_is_offered_strictly()
            )
        )


def _every_tool_is_named_in(names: set[str]) -> Assertion[list[ToolDefinition]]:
    """Exactly the offered set, and nothing that is not in it."""
    def assertion(tools: list[ToolDefinition]) -> bool:
        offered = {tool.name for tool in tools}
        if offered != names:
            raise AssertionError(f"Expected the tools {sorted(names)}, got {sorted(offered)}.")

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
