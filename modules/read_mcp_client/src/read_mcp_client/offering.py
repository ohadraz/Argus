"""What an agent offers a model of the read tier: the tools it holds, as the
server declares them.

The server owns each tool's definition (MCP, `tools/list`) and an agent offers
what it declares rather than keeping a copy - filtered to the tools it holds by
name, as an agent SDK's tool filter does, and less the arguments it fills in
itself, as LangChain's `InjectedToolArg` does. That is what keeps the
Investigator read-only on a tier that serves Code-Fix too: the tier says what
can be read, and each agent says what it holds.

The definitions are the server's; which tools an agent offers, and in what
order, is the agent's prompt - so the order is the one the agent holds them in.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from argus_core.mcp_transport import McpClient
from argus_core.models import ToolDefinition


class NotServed(LookupError):
    """An agent holds a tool the read tier does not serve.

    Raised rather than left out: an agent offered fewer tools than it was
    built to hold investigates with a channel missing and never says so.
    """


def offered(holds: Mapping[str, Collection[str]],
            *,
            client: McpClient) -> list[ToolDefinition]:
    """The tools `holds` names, as the server declares them, in the order
    `holds` names them - each less the arguments `holds` says its caller fills
    in.

    Only the tools held are read into an offer: a tool no agent offers may
    have an argument no offer could carry, and that is nobody's to refuse.
    In the server's order, a registration moved in the server would rewrite
    every agent's prompt with nothing saying so.
    """
    served = {tool.name: tool for tool in client.list_tools()}
    missing = [name for name in holds if name not in served]

    if missing:
        raise NotServed(f"the read tier serves no {missing}")

    return [
        ToolDefinition.from_input_schema(
            name, served[name].description, served[name].inputSchema
        ).without(*bound)
        for name, bound in holds.items()
    ]
