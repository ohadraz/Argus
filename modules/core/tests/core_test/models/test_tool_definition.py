"""What Argus offers the model, in Argus's own terms.

A tool is described here as what a caller decides - its name, when to reach
for it, and what it may be asked for - and the rules that make such a
description coherent: nothing required that is not offered, and nothing taken
from a server that an offer could not carry. How an offer looks on the wire is
the provider adapter's (`llm/adapters/test_tool_offers.py`), and nothing here
renders one.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from core.models.tool_definition import ToolDefinition
from pydantic import ValidationError


@pytest.mark.unit
def test_a_tool_cannot_require_an_argument_it_does_not_offer() -> None:
    # A schema demanding a property it never declared is malformed, and the API
    # rejects the whole request rather than the one tool - so a typo in one
    # tool's required list takes the entire investigation down with it.
    #
    # Caught at construction, where the tool is written, rather than at the
    # call, where the failure names an HTTP status and not the mistake. The
    # same reason `Hypothesis` refuses a cause without a confidence: a type
    # that can hold an incoherent value will eventually be handed one.
    some_offered_argument = {"window_start": {"type": "string"}}
    an_argument_never_offered = "window_end"

    Scenario() \
        .when(
            attempting(
                lambda: a_tool_definition(properties=some_offered_argument,
                                          required=[an_argument_never_offered])
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_tool_read_from_its_server_offers_what_the_server_declared() -> None:
    # The server owns a tool's definition (MCP, "tools/list"), and what it
    # declares is what the model is offered. Less the titles its schema
    # generator writes on every node: they say nothing a description does not,
    # and strict tool use lists no support for them.
    some_description = "Returns one file of the repository."
    the_servers_schema = {
        "type": "object",
        "title": "read_repository_fileArguments",
        "properties": {
            "path": {"type": "string", "title": "Path", "description": "From the root."},
            "window_start": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Window Start"
            }
        },
        "required": ["path"]
    }

    Scenario() \
        .when(
            lambda: ToolDefinition.from_input_schema(
                "read_repository_file", some_description, the_servers_schema
            )
        ) \
        .then(
            all_of(
                _it_is_named("read_repository_file"),
                _it_is_described_as(some_description),
                _it_offers({
                    "path": {"type": "string", "description": "From the root."},
                    "window_start": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "default": None
                    }
                }),
                _it_requires(["path"])
            )
        )


@pytest.mark.unit
def test_an_argument_named_title_is_an_argument_and_not_a_title() -> None:
    # The titles dropped are schema keywords. A tool taking an argument called
    # `title` names it as a key of `properties`, and losing it would offer the
    # model a tool it cannot fully call.
    the_servers_schema = {
        "type": "object",
        "properties": {"title": {"type": "string", "title": "Title"}},
        "required": ["title"]
    }

    Scenario() \
        .when(
            lambda: ToolDefinition.from_input_schema(
                "dont_care_tool", "dont care what it does", the_servers_schema
            )
        ) \
        .then(
            _it_offers({"title": {"type": "string"}})
        )


@pytest.mark.unit
def test_an_argument_the_caller_fills_in_is_neither_offered_nor_required() -> None:
    # Which branch Code-Fix reads is Code-Fix's to say, not the model's: an
    # argument the agent binds itself is taken out of what the model sees
    # (LangChain's InjectedToolArg), from `required` as well as `properties`,
    # or the API refuses a schema demanding what it does not offer.
    some_tool = a_tool_definition(
        properties={"path": {"type": "string"}, "ref": {"type": "string"}},
        required=["path", "ref"]
    )

    Scenario() \
        .when(
            lambda: some_tool.without("ref")
        ) \
        .then(
            all_of(
                _it_offers({"path": {"type": "string"}}),
                _it_requires(["path"])
            )
        )


@pytest.mark.unit
def test_an_argument_defined_elsewhere_in_the_servers_schema_is_refused() -> None:
    # A pydantic model as an argument reaches the schema as a `$ref` into the
    # schema's own `$defs`, which an offer of properties alone leaves pointing
    # at nothing - and the API refuses the whole request over it. Refused here
    # instead, naming the argument, the day such a tool is offered.
    the_servers_schema = {
        "type": "object",
        "properties": {"descriptor": {"$ref": "#/$defs/RollbackUndo"}},
        "required": ["descriptor"],
        "$defs": {"RollbackUndo": {"type": "object", "properties": {}}}
    }

    Scenario() \
        .when(
            attempting(lambda: ToolDefinition.from_input_schema(
                "dont_care_tool", "dont care what it does", the_servers_schema
            ))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("descriptor")
            )
        )


@pytest.mark.unit
def test_a_map_argument_is_refused_since_a_strict_offer_cannot_say_it() -> None:
    # A map is an object whose keys are anybody's. Strict tool use takes
    # objects that name their keys and forbid the rest, so a map stamped strict
    # would be an object taking no keys at all - wrong without anything saying so.
    the_servers_schema = {
        "type": "object",
        "properties": {
            "files": {"type": "object", "additionalProperties": {"type": "string"}}
        },
        "required": ["files"]
    }

    Scenario() \
        .when(
            attempting(lambda: ToolDefinition.from_input_schema(
                "dont_care_tool", "dont care what it does", the_servers_schema
            ))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("files")
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("argument_schema", [
    {"type": "object"},
    {"type": "object", "properties": {"path": {"type": "string"}}, "additionalProperties": True}
], ids=["names-no-keys", "takes-keys-it-does-not-name"])
def test_an_object_taking_keys_it_does_not_name_is_refused(
        argument_schema: dict[str, Any]) -> None:
    # A strict offer closes every object to the keys it names. One naming none
    # would then take nothing, and one open to any key would quietly stop taking
    # the keys it never named - either way an offer saying less than the server.
    the_servers_schema = {
        "type": "object",
        "properties": {"files": argument_schema},
        "required": ["files"]
    }

    Scenario() \
        .when(
            attempting(lambda: ToolDefinition.from_input_schema(
                "dont_care_tool", "dont care what it does", the_servers_schema
            ))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("files")
            )
        )


@pytest.mark.unit
def test_leaving_out_an_argument_the_tool_does_not_take_is_refused() -> None:
    # A server that renamed an argument its caller fills in would otherwise
    # have it offered to the model again, under its new name, with nothing
    # saying the two had drifted apart.
    some_tool = a_tool_definition(properties={"path": {"type": "string"}},
                                  required=["path"])

    Scenario() \
        .when(
            attempting(lambda: some_tool.without("ref"))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValueError),
                the_error_mentioned("ref")
            )
        )


def _it_is_named(name: str) -> Assertion[ToolDefinition]:
    """The name the model calls, and the dispatcher looks up."""
    def assertion(tool: ToolDefinition) -> bool:
        if tool.name != name:
            raise AssertionError(f"Expected the tool to be named [{name}], got [{tool.name}].")

        return True

    return assertion


def _it_is_described_as(description: str) -> Assertion[ToolDefinition]:
    """What tells the model when to reach for this tool rather than another."""
    def assertion(tool: ToolDefinition) -> bool:
        if tool.description != description:
            raise AssertionError(
                f"Expected the tool to be described as [{description}], "
                f"got [{tool.description}]."
            )

        return True

    return assertion


def _it_offers(properties: dict[str, Any]) -> Assertion[ToolDefinition]:
    """The arguments the model may name."""
    def assertion(tool: ToolDefinition) -> bool:
        if tool.properties != properties:
            raise AssertionError(
                f"Expected the tool to offer {properties}, got {tool.properties}."
            )

        return True

    return assertion


def _it_requires(required: list[str]) -> Assertion[ToolDefinition]:
    """The arguments the model may not leave out."""
    def assertion(tool: ToolDefinition) -> bool:
        if tool.required != required:
            raise AssertionError(
                f"Expected the tool to require {required}, got {tool.required}."
            )

        return True

    return assertion


def a_tool_definition(name: str = "get_logs",
                      description: str = "dont care what it does",
                      properties: dict[str, Any] | None = None,
                      required: list[str] | None = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        properties=properties if properties is not None else {},
        required=required if required is not None else []
    )
