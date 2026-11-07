"""That no tool tells a model to reach for a tool it was not offered.

A read-tier tool's description is the server's, and one description is shared
by every agent and every way of finding source that offers the tool. So a
description naming another tool is right only where every offer holding it
holds that one too: `list_repository_files` saying "prefer search_repository"
is advice in a deployment that searches by grep, and in one that searches by
meaning alone it points the model at nothing - which it will try to call.

Each offer is built as a real one is, from the server's own listing, and every
description in it - the tool's and each argument's - is read for the name of
any tool anybody serves or holds.
"""

from __future__ import annotations

import json
import re

import pytest
from agent_codefix.tools import READ_TIER_HELD as CODE_FIX_HELD
from agent_codefix.tools import tools_for
from agent_investigator.tools import READ_TIER_HELD as INVESTIGATOR_HELD
from agent_investigator.tools import investigator_tools
from agent_investigator.tools.weighing import weigh_lead_tool
from argus_core.models import CodeSearch, ToolDefinition
from argus_testkit import Assertion, Scenario

from tests.framework.read_tier import every_tool_the_read_tier_lists, what_the_read_tier_offers


def _the_investigators_offer() -> list[ToolDefinition]:
    return [
        *investigator_tools(what_the_read_tier_offers(INVESTIGATOR_HELD)),
        weigh_lead_tool()
    ]


def _code_fixs_offer(mode: CodeSearch) -> list[ToolDefinition]:
    return tools_for(what_the_read_tier_offers(CODE_FIX_HELD[mode], mode))


@pytest.mark.integration
def test_the_investigator_is_pointed_at_no_tool_it_was_not_offered() -> None:
    Scenario() \
        .when(_the_investigators_offer) \
        .then(_names_no_tool_outside_itself(_every_tool_anybody_names()))


@pytest.mark.integration
@pytest.mark.parametrize("mode", list(CodeSearch), ids=[mode.value for mode in CodeSearch])
def test_code_fix_is_pointed_at_no_tool_it_was_not_offered(mode: CodeSearch) -> None:
    Scenario() \
        .when(lambda: _code_fixs_offer(mode)) \
        .then(_names_no_tool_outside_itself(_every_tool_anybody_names()))


def _every_tool_anybody_names() -> set[str]:
    """Every tool the read tier lists in its widest deployment, and every tool
    an agent offers of its own."""
    return {
        *every_tool_the_read_tier_lists(CodeSearch.BOTH),
        *(tool.name for tool in _the_investigators_offer()),
        *(tool.name for tool in _code_fixs_offer(CodeSearch.BOTH))
    }


def _names_no_tool_outside_itself(known: set[str]) -> Assertion[list[ToolDefinition]]:
    def assertion(offered: list[ToolDefinition]) -> bool:
        on_offer = {tool.name for tool in offered}
        stray = {
            tool.name: sorted(name for name in known - on_offer
                              if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", _said_by(tool)))
            for tool in offered
        }
        stray = {tool: names for tool, names in stray.items() if names}

        if stray:
            raise AssertionError(
                f"Expected every tool a description names to be on offer beside it, and "
                f"these name tools this offer does not hold: {stray}."
            )

        return True

    return assertion


def _said_by(tool: ToolDefinition) -> str:
    """Everything the tool says to a model: its description and every argument's."""
    return tool.description + "\n" + json.dumps(tool.properties)
