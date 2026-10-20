"""What Code-Fix is given, taken as a whole.

The guarantee this agent rests on is the absence of a capability, not a check
somebody could skip (§13): it reads a repository and proposes a patch, and
nothing it holds runs, merges or reaches the service. So what it holds is
asserted rather than assumed - the reads it holds of the read tier, for each way
a deployment finds source, and what it offers beside them.

The reads are the read tier's, which serves the Investigator's as well, and
what each says to a model is the server's to declare; what is held here is
which of them Code-Fix offers, in what order, and which argument it fills in.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

import pytest
from agent_codefix.tools import READ_TIER_HELD, tools_for
from argus_core.models import CodeSearch, ToolDefinition
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVED_TOOLS = [
    ToolDefinition(name="some_read",
                   description="dont care what it reads",
                   properties={"path": {"type": "string"}},
                   required=["path"]),
    ToolDefinition(name="another_read",
                   description="dont care what it reads",
                   properties={},
                   required=[])
]


@pytest.mark.unit
@pytest.mark.parametrize("mode, held", [
    # Searching first, because the opening tells the model to start there.
    (CodeSearch.GREP, ["search_repository",
                       "list_repository_files",
                       "read_repository_file"]),
    # One channel at a time, over the same incidents, is what the benchmark's
    # retriever comparison (§21) needs.
    (CodeSearch.MEANING, ["search_repository_by_meaning",
                          "list_repository_files",
                          "read_repository_file"]),
    # One matches characters and the other meaning; a cause with a name is
    # found faster by the first, and one with only a description at all by the
    # second.
    (CodeSearch.BOTH, ["search_repository",
                       "search_repository_by_meaning",
                       "list_repository_files",
                       "read_repository_file"])
], ids=["grep", "meaning", "both"])
def test_code_fix_holds_the_reads_its_deployment_finds_source_by_and_fills_in_the_ref(
        mode: CodeSearch, held: list[str]) -> None:
    # A deployment with no index holds no search by meaning: a tool that is
    # offered will be called, and one backed by an index nobody built answers
    # nothing, which a model reads as a fact about the code. The ref is the
    # branch a fix is cut from, never the model's to name.
    Scenario() \
        .when(lambda: READ_TIER_HELD[mode]) \
        .then(_the_holding_is([(name, {"ref"}) for name in held]))


@pytest.mark.unit
def test_code_fix_offers_what_the_read_tier_serves_and_three_ways_to_answer() -> None:
    # Pinned as the whole list rather than asserted as the absence of a name
    # nobody has written: a tool that ran something would be added under a name
    # this test cannot predict. The report is offered alongside the patch, not
    # instead of it - a model that can propose but not conclude has only a fix
    # for an answer, however the code reads.
    Scenario() \
        .when(lambda: tools_for(SOME_SERVED_TOOLS)) \
        .then(all_of(
            _the_tools_offered_are([
                *(tool.name for tool in SOME_SERVED_TOOLS),
                "submit_fix",
                "report_nothing_to_change",
                "answer_question"
            ]),
            _every_tool_is_offered_strictly()
        ))


def _the_holding_is(expected: list[tuple[str, set[str]]]
                    ) -> Assertion[Mapping[str, Collection[str]]]:
    """Exactly the tools held, in the order offered, each with the arguments
    its caller fills in."""
    def assertion(held: Mapping[str, Collection[str]]) -> bool:
        actual = [(name, set(bound)) for name, bound in held.items()]

        if actual != expected:
            raise AssertionError(f"Expected the read tier held as {expected}, got {actual}.")

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
    """No tool may accept an argument the loop was not written for."""
    def assertion(tools: list[ToolDefinition]) -> bool:
        loose = [tool.name for tool in tools if tool.to_wire().get("strict") is not True]

        if loose:
            raise AssertionError(f"Expected every tool to be strict, but {loose} were not.")

        return True

    return assertion
