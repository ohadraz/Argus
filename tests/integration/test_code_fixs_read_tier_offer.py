"""That what the read tier offers Code-Fix is what Code-Fix reads back, and is
what the model has always been offered.

The read tier declares each repository tool Code-Fix offers, and Code-Fix
answers each call by reading its arguments under names of its own. No compiler
joins the two: a server that renamed an argument would have every call answered
about an empty string, and one that gained an argument would have it offered to
the model and dropped in silence. So the offer is built as a real one is - the
server's own listing, through the read client's own `offered` - for each way a
deployment finds source, and its arguments are held to exactly the ones read
back.

And the offer whole is pinned for each, as the request carries it. No replay
sees it change - the model double answers a recording whatever it was asked -
so an SDK that wrote a schema another way, or a description that moved, would
reach the model unreviewed. A change to the pinned offer is a change to what
the model reads, made on purpose, and re-recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from argus_testkit import Assertion, Scenario
from codefix_agent.tools import (
    DESCRIPTION_ARGUMENT,
    LIST_FILES_TOOL,
    PATH_ARGUMENT,
    QUERY_ARGUMENT,
    READ_FILE_TOOL,
    READ_TIER_HELD,
    SEARCH_BY_MEANING_TOOL,
    SEARCH_TOOL,
)
from core.models import CodeSearch, ToolDefinition
from llm_anthropic import to_tool

from tests.framework.read_tier import what_the_read_tier_offers

# What Code-Fix reads back from each call, by tool.
READ_BACK = {
    SEARCH_TOOL: {QUERY_ARGUMENT},
    SEARCH_BY_MEANING_TOOL: {DESCRIPTION_ARGUMENT},
    LIST_FILES_TOOL: set(),
    READ_FILE_TOOL: {PATH_ARGUMENT}
}

# The offer as the request carries it, for each way of finding source: every
# tool held, in order, each as the model adapter renders it.
THE_OFFERS_PINNED = Path(__file__).with_name("code_fixs_read_tier_offer.json")


@pytest.mark.integration
@pytest.mark.parametrize("mode", list(CodeSearch), ids=[mode.value for mode in CodeSearch])
def test_the_read_tier_offers_code_fix_only_what_it_reads_back(mode: CodeSearch) -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD[mode], mode)) \
        .then(_each_tool_takes_exactly({name: READ_BACK[name] for name in READ_TIER_HELD[mode]}))


@pytest.mark.integration
@pytest.mark.parametrize("mode", list(CodeSearch), ids=[mode.value for mode in CodeSearch])
def test_the_read_tier_offers_code_fix_the_offer_pinned(mode: CodeSearch) -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD[mode], mode)) \
        .then(_rendered_as_pinned(
            json.loads(THE_OFFERS_PINNED.read_text(encoding="utf-8"))[mode.value], mode
        ))


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


def _rendered_as_pinned(pinned: object, mode: CodeSearch) -> Assertion[list[ToolDefinition]]:
    """The offer, rendered, compared as text: a map's keys in another order are
    another request, which comparing the maps would not see."""
    def assertion(offered: list[ToolDefinition]) -> bool:
        rendered = json.dumps([to_tool(tool) for tool in offered], ensure_ascii=False)
        expected = json.dumps(pinned, ensure_ascii=False)

        if rendered != expected:
            raise AssertionError(
                f"Expected Code-Fix offered the read tier's tools, finding source by "
                f"[{mode.value}], as pinned in [{THE_OFFERS_PINNED.name}], and they are "
                f"offered as {rendered}."
            )

        return True

    return assertion
