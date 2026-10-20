"""That what the read tier offers Code-Fix is what Code-Fix reads back.

The read tier declares each repository tool Code-Fix offers, and Code-Fix
answers each call by reading its arguments under names of its own. No compiler
joins the two: a server that renamed an argument would have every call answered
about an empty string, and one that gained an argument would have it offered to
the model and dropped in silence. So the offer is built as a real one is - the
server's own listing, through the read client's own `offered` - for each way a
deployment finds source, and its arguments are held to exactly the ones read
back.
"""

from __future__ import annotations

import pytest
from agent_codefix.tools import (
    DESCRIPTION_ARGUMENT,
    LIST_FILES_TOOL,
    PATH_ARGUMENT,
    QUERY_ARGUMENT,
    READ_FILE_TOOL,
    READ_TIER_HELD,
    SEARCH_BY_MEANING_TOOL,
    SEARCH_TOOL,
)
from argus_core.models import CodeSearch, ToolDefinition
from argus_testkit import Assertion, Scenario

from tests.framework.read_tier import what_the_read_tier_offers

# What Code-Fix reads back from each call, by tool.
READ_BACK = {
    SEARCH_TOOL: {QUERY_ARGUMENT},
    SEARCH_BY_MEANING_TOOL: {DESCRIPTION_ARGUMENT},
    LIST_FILES_TOOL: set(),
    READ_FILE_TOOL: {PATH_ARGUMENT}
}


@pytest.mark.integration
@pytest.mark.parametrize("mode", list(CodeSearch), ids=[mode.value for mode in CodeSearch])
def test_the_read_tier_offers_code_fix_only_what_it_reads_back(mode: CodeSearch) -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD[mode], mode)) \
        .then(_each_tool_takes_exactly({name: READ_BACK[name] for name in READ_TIER_HELD[mode]}))


def _each_tool_takes_exactly(expected: dict[str, set[str]]) -> Assertion[list[ToolDefinition]]:
    def assertion(offered: list[ToolDefinition]) -> bool:
        taken = {tool.name: set(tool.properties) for tool in offered}

        if taken != expected:
            raise AssertionError(
                f"Expected the read tier to offer Code-Fix {expected}, and it offers "
                f"{taken}."
            )

        return True

    return assertion
