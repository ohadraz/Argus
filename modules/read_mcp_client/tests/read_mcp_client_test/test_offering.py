"""What an agent is offered of the read tier: the tools it holds, as the server
declares them.

The server owns each tool's definition and the agent offers what it declares
(MCP, `tools/list`), filtered to the tools it holds by name - the way an agent
SDK's tool filter does - in the order it holds them, and less the arguments it
fills in itself. The server
is stood in for here: what is under test is the filtering, and the listing
itself is the transport's.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.mcp_transport import McpClient
from argus_core.models import ToolDefinition
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from argus_testkit.assertions import the_error_mentioned
from mcp.types import Tool
from read_mcp_client import NotServed, offered

SOME_ARGUMENT = {"type": "string"}


@pytest.mark.unit
def test_an_agent_is_offered_the_tools_it_holds_in_the_order_it_holds_them() -> None:
    # The definitions are the server's; which tools an agent offers, and in what
    # order, is the agent's prompt. In the server's order, a registration moved
    # in the server would rewrite every agent's prompt with nothing saying so.
    some_server = _a_server_listing("get_logs", "get_rollout_state", "get_metrics")

    Scenario() \
        .when(
            lambda: offered({"get_metrics": frozenset(), "get_logs": frozenset()},
                            client=some_server)
        ) \
        .then(
            _the_tools_offered_are(["get_metrics", "get_logs"])
        )


@pytest.mark.unit
def test_a_tool_no_agent_holds_is_not_read_into_an_offer() -> None:
    # A tool whose argument no strict offer can carry is refused as an offer -
    # and a server may serve one that no agent offers. Read into an offer
    # regardless, it would leave every agent of that server offered nothing.
    some_server = _a_server_listing("get_logs")
    some_server.list_tools.return_value.append(Tool(
        name="restore_deployment",
        description="dont care what it does",
        inputSchema={"type": "object",
                     "properties": {"descriptor": {"$ref": "#/$defs/RollbackUndo"}},
                     "required": ["descriptor"]}
    ))

    Scenario() \
        .when(
            lambda: offered({"get_logs": frozenset()}, client=some_server)
        ) \
        .then(
            _the_tools_offered_are(["get_logs"])
        )


@pytest.mark.unit
def test_an_argument_the_agent_fills_in_is_taken_out_of_what_it_is_offered() -> None:
    # Which branch Code-Fix reads is Code-Fix's to say. Left in, the model would
    # be asked for a value it has no way to know and every call would carry its
    # guess.
    some_server = _a_server_listing("read_repository_file", properties=["path", "ref"])

    Scenario() \
        .when(
            lambda: offered({"read_repository_file": frozenset({"ref"})}, client=some_server)
        ) \
        .then(
            all_of(
                _the_tool_offered_takes("read_repository_file", ["path"]),
                _the_tool_offered_requires("read_repository_file", ["path"])
            )
        )


@pytest.mark.unit
def test_a_tool_the_server_does_not_serve_is_refused_rather_than_left_out() -> None:
    # An agent offered fewer tools than it was built to hold investigates with a
    # channel missing and never says so. Refused, the walk fails where a person
    # sees it.
    some_server = _a_server_listing("get_logs")

    Scenario() \
        .when(
            attempting(lambda: offered({"get_logs": frozenset(),
                                        "get_rollout_state": frozenset()},
                                       client=some_server))
        ) \
        .then(
            all_of(
                an_error_was_raised(NotServed),
                the_error_mentioned("get_rollout_state")
            )
        )


def _a_server_listing(*names: str, properties: list[str] | None = None) -> Any:
    """A read tier listing these tools, in this order, each taking and
    requiring `properties`."""
    taken = properties if properties is not None else []
    server = create_autospec(McpClient, instance=True)
    server.list_tools.return_value = [
        Tool(name=name, description="dont care what it does",
             inputSchema={"type": "object",
                          "properties": {argument: SOME_ARGUMENT for argument in taken},
                          "required": list(taken)})
        for name in names
    ]

    return server


def _the_tools_offered_are(expected: list[str]) -> Assertion[list[ToolDefinition]]:
    def assertion(tools: list[ToolDefinition]) -> bool:
        names = [tool.name for tool in tools]

        if names != expected:
            raise AssertionError(f"Expected the agent offered {expected}, got {names}.")

        return True

    return assertion


def _the_tool_offered_takes(name: str, expected: list[str]) -> Assertion[list[ToolDefinition]]:
    def assertion(tools: list[ToolDefinition]) -> bool:
        taken = list(_the_one_named(tools, name).properties)

        if taken != expected:
            raise AssertionError(f"Expected [{name}] offered taking {expected}, got {taken}.")

        return True

    return assertion


def _the_tool_offered_requires(name: str,
                               expected: list[str]) -> Assertion[list[ToolDefinition]]:
    def assertion(tools: list[ToolDefinition]) -> bool:
        required = _the_one_named(tools, name).required

        if required != expected:
            raise AssertionError(f"Expected [{name}] offered requiring {expected}, got "
                                 f"{required}.")

        return True

    return assertion


def _the_one_named(tools: list[ToolDefinition], name: str) -> ToolDefinition:
    found = [tool for tool in tools if tool.name == name]

    if len(found) != 1:
        raise AssertionError(f"Expected one tool offered named [{name}], got {len(found)}.")

    return found[0]
