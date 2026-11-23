"""That what the read tier offers the Investigator is what its dispatcher reads,
and is what the model has always been offered.

The read tier declares each tool the Investigator offers from it, and the
Investigator's dispatcher reads each call's arguments by names of its own. No
compiler joins the two: a server that renamed an argument would have every call
refused, and one that gained an argument would have it offered to the model and
dropped by the dispatcher in silence. So the offer is built as a real one is -
the server's own listing, through the read client's own `offered` - and its
arguments are held to exactly the ones read back.

And the offer whole is pinned, as the request carries it. No replay sees it
change - the model double answers a recording whatever it was asked - so an SDK
that wrote a schema another way, or a description that moved, would reach the
model unreviewed. A change to the pinned offer is a change to what the model
reads, made on purpose, and re-recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from argus_testkit import Assertion, Scenario
from core.models import ToolDefinition
from investigation_agent.tools import (
    DEPENDENCIES_TOOL,
    DEPLOYMENT_DIFF_TOOL,
    READ_TIER_HELD,
    ROLLOUT_TOOL,
)
from investigation_agent.tools.deployments import REVISION_ARG
from llm_anthropic import to_tool

from tests.framework.read_tier import what_the_read_tier_offers

# The offer as the request carries it: every tool held, in order, each as the
# model adapter renders it.
THE_OFFER_PINNED = Path(__file__).with_name("the_investigators_read_tier_offer.json")


@pytest.mark.integration
def test_the_read_tier_offers_the_investigator_only_what_its_dispatcher_reads() -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD)) \
        .then(_each_tool_takes_exactly({
            DEPENDENCIES_TOOL: set(),
            DEPLOYMENT_DIFF_TOOL: {REVISION_ARG},
            ROLLOUT_TOOL: set()
        }))


@pytest.mark.integration
def test_the_read_tier_offers_the_investigator_the_offer_pinned() -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD)) \
        .then(_rendered_as_pinned(json.loads(THE_OFFER_PINNED.read_text(encoding="utf-8"))))


def _each_tool_takes_exactly(expected: dict[str, set[str]]) -> Assertion[list[ToolDefinition]]:
    def assertion(offered: list[ToolDefinition]) -> bool:
        taken = {tool.name: set(tool.properties) for tool in offered}

        if taken != expected:
            raise AssertionError(
                f"Expected the read tier to offer the Investigator {expected}, and it "
                f"offers {taken}."
            )

        return True

    return assertion


def _rendered_as_pinned(pinned: object) -> Assertion[list[ToolDefinition]]:
    """The offer, rendered, compared as text: a map's keys in another order are
    another request, which comparing the maps would not see."""
    def assertion(offered: list[ToolDefinition]) -> bool:
        rendered = json.dumps([to_tool(tool) for tool in offered], ensure_ascii=False)
        expected = json.dumps(pinned, ensure_ascii=False)

        if rendered != expected:
            raise AssertionError(
                f"Expected the Investigator offered the read tier's tools as pinned in "
                f"[{THE_OFFER_PINNED.name}], and they are offered as {rendered}."
            )

        return True

    return assertion
