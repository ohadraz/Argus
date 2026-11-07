"""Every tool the Investigator is offered, assembled in one place.

The tier boundary is this list. The Investigator is read-only because of what
it possesses, not because a prompt asks it to behave, so a write tool
appearing here is the one failure in this package that matters most - and the
reason the offered set is asserted in a test rather than assumed.

Three of its reads are the read tier's, which serves Code-Fix's reads as well.
Those are held here by name and offered as the server declares them (MCP,
`tools/list`), so what each says to a model is written once, by the server
that answers it - and what is held here is what keeps the Investigator to its
own three on a tier that serves more.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from functools import partial
from typing import Final, Protocol

from argus_core.mcp_transport import McpClient
from argus_core.models import ToolDefinition
from read_mcp_client import offered

from agent_investigator.tools.answer import answer_tool
from agent_investigator.tools.changes import changes_tool
from agent_investigator.tools.dependencies import DEPENDENCIES_TOOL
from agent_investigator.tools.deployments import DEPLOYMENT_DIFF_TOOL
from agent_investigator.tools.logs import logs_tool
from agent_investigator.tools.metrics import metrics_tool
from agent_investigator.tools.rollouts import ROLLOUT_TOOL

# The argument every read-tier tool held here is asked about. The service is
# the incident's, so the dispatcher fills it in and the model is never offered it.
_SERVICE_ARG: Final = "service"

# The read tier's tools the Investigator holds, each with the arguments it fills
# in itself - in the order they are offered, which is the prompt's.
READ_TIER_HELD: Final[Mapping[str, Collection[str]]] = {
    DEPENDENCIES_TOOL: frozenset({_SERVICE_ARG}),
    DEPLOYMENT_DIFF_TOOL: frozenset({_SERVICE_ARG}),
    ROLLOUT_TOOL: frozenset({_SERVICE_ARG})
}


class ReadTierTools(Protocol):
    """The read tier's tools the Investigator holds, as the tier declares them.

    Asked once an investigation reaches its model, never before every turn:
    what a tier serves does not change mid-investigation.
    """

    def __call__(self) -> list[ToolDefinition]: ...


def read_tier_tools_over(client: McpClient) -> ReadTierTools:
    """The read tier's tools held here, asked over one connection to it.

    Bound where a process starts, as every channel is, so the loop is handed
    the offer rather than the means to ask for one.
    """
    return partial(offered, READ_TIER_HELD, client=client)


def investigator_tools(read_tier: Sequence[ToolDefinition]) -> list[ToolDefinition]:
    """Every tool the Investigator is offered, and nothing else.

    Six retrievals and one way to finish. The first three are the loop's own and
    take their own optional window, because which minutes are worth reading is
    the model's decision to make once it has seen something - and leaving a
    window out is also a decision, answered by each channel's own default rather
    than by the model guessing at an anchor it was already told.

    The other three are `read_tier`'s - the register, the deployment diff and
    the rollout - and none of them is a window over time: what a service calls,
    what a deployment changed and how far its rollout got are facts about how it
    is built and what is running now. They are offered in the order the tier was
    asked for them, between the windowed reads and the way to finish.
    """
    return [
        metrics_tool(),
        logs_tool(),
        changes_tool(),
        *read_tier,
        answer_tool()
    ]
