"""That what the read tier offers the Investigator is what its dispatcher reads.

The read tier declares each tool the Investigator offers from it, and the
Investigator's dispatcher reads each call's arguments by names of its own. No
compiler joins the two: a server that renamed an argument would have every call
refused, and one that gained an argument would have it offered to the model and
dropped by the dispatcher in silence. So the offer is built as a real one is -
the server's own listing, through the read client's own `offered` - and its
arguments are held to exactly the ones read back.
"""

from __future__ import annotations

import pytest
from agent_investigator.tools import (
    DEPENDENCIES_TOOL,
    DEPLOYMENT_DIFF_TOOL,
    READ_TIER_HELD,
    ROLLOUT_TOOL,
)
from agent_investigator.tools.deployments import REVISION_ARG
from argus_core.models import ToolDefinition
from argus_testkit import Assertion, Scenario

from tests.framework.read_tier import what_the_read_tier_offers


@pytest.mark.integration
def test_the_read_tier_offers_the_investigator_only_what_its_dispatcher_reads() -> None:
    Scenario() \
        .when(lambda: what_the_read_tier_offers(READ_TIER_HELD)) \
        .then(_each_tool_takes_exactly({
            DEPENDENCIES_TOOL: set(),
            DEPLOYMENT_DIFF_TOOL: {REVISION_ARG},
            ROLLOUT_TOOL: set()
        }))


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
