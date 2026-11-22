"""The wire shape a tool offer takes, as Anthropic is sent it.

The counterpart to `test_to_turn.py`: that file covers a reply coming back,
this one covers the tools going out. Offline for the same reason - what is
under test is the translation, not the call.

A tool is described in Argus's own terms (`ToolDefinition`) and rendered into
Anthropic's only here, at the edge. The rendering is where the strictness rules
live: a schema that forgets `additionalProperties` silently stops being strict,
and nothing downstream notices until the model sends an argument nobody
handles.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from anthropic.types import ToolParam
from argus_testkit import Assertion, Scenario, all_of
from core.models import ToolDefinition
from llm_anthropic import to_tool

# Anthropic's own vocabulary for a tool offer. Stated here rather than imported
# from the code under test: a test that borrowed the adapter's spelling would
# agree with it even when both are wrong.
NAME_KEY: Final = "name"
DESCRIPTION_KEY: Final = "description"
INPUT_SCHEMA_KEY: Final = "input_schema"
STRICT_KEY: Final = "strict"

TYPE_KEY: Final = "type"
PROPERTIES_KEY: Final = "properties"
REQUIRED_KEY: Final = "required"
ADDITIONAL_PROPERTIES_KEY: Final = "additionalProperties"

OBJECT_TYPE: Final = "object"


@pytest.mark.unit
def test_a_tool_is_offered_by_name_and_description() -> None:
    # The description is not decoration: it is the only thing telling the model
    # when this tool is the right one to reach for. A rendering that dropped it
    # would leave the model choosing between names alone.
    some_tool_name = "get_logs"
    some_description = "Return the service's log lines for a time window."

    Scenario() \
        .given(
            some_tool := a_tool_definition(name=some_tool_name,
                                           description=some_description)
        ) \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            all_of(
                _the_offer_names(some_tool_name),
                _the_offer_describes_it_as(some_description)
            )
        )


@pytest.mark.unit
def test_the_arguments_a_tool_takes_reach_the_model_as_its_schema() -> None:
    # What the model is allowed to ask for. These become the window on a
    # retrieval call, so a property lost here is a question the model cannot
    # ask however clearly it wants to.
    some_properties = {
        "window_start": {"type": "string"},
        "window_end": {"type": "string"}
    }
    some_required = ["window_start"]

    Scenario() \
        .given(
            some_tool := a_tool_definition(properties=some_properties,
                                           required=some_required)
        ) \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            all_of(
                _the_schema_offers(some_properties),
                _the_schema_requires(some_required)
            )
        )


@pytest.mark.unit
def test_every_tool_is_offered_strictly() -> None:
    # Strictness is not a per-tool choice. The dispatcher looks the tool up by
    # name and calls it with what arrived; an argument the schema never
    # promised is one nothing is written to handle. Strict mode is what makes
    # the arguments a dispatcher receives exactly the arguments it declared.
    #
    # `additionalProperties: false` is half of that and easy to omit, which is
    # why it is rendered here rather than left to each caller: a schema missing
    # it is quietly permissive, and no test of that tool would show it.
    Scenario() \
        .given(
            some_tool := a_tool_definition()
        ) \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            all_of(
                _the_offer_is_strict(),
                _the_schema_forbids_anything_else(),
                _the_schema_describes_an_object()
            )
        )


@pytest.mark.unit
def test_an_object_nested_inside_a_tools_arguments_is_strict_too() -> None:
    # A tool whose argument is a list of records - a patch of whole files, each
    # a path and its contents - carries an object the caller wrote rather than
    # one this rendering built. The API demands the same strictness of that one,
    # and refuses the entire request when it does not get it: one tool with a
    # permissive nested object takes every other tool in the call down with it.
    #
    # So the rendering stamps it wherever an object appears, for the reason it
    # stamps the outer one - a caller writing `additionalProperties` at every
    # depth is a caller who will one day write it at all but one.
    a_patch_of_whole_files = {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    }

    Scenario() \
        .given(
            some_tool := a_tool_definition(properties=a_patch_of_whole_files,
                                           required=["files"])
        ) \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            all_of(
                _the_schema_forbids_anything_else(),
                _every_nested_object_forbids_anything_else()
            )
        )


@pytest.mark.unit
def test_stamping_an_offer_strict_leaves_the_definition_as_it_was_written() -> None:
    # A tool's properties are usually a module-level constant somebody wrote.
    # Stamped where they lie, the first offer would rewrite the definition
    # itself, and every later reader of it would see an offer rather than what
    # was written.
    a_nested_record = {
        "files": {
            "type": "array",
            "items": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"]}
        }
    }
    some_tool = a_tool_definition(properties=a_nested_record, required=["files"])

    Scenario() \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            _the_definition_still_reads(some_tool, {
                "files": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"path": {"type": "string"}},
                              "required": ["path"]}
                }
            })
        )


@pytest.mark.unit
def test_a_tool_that_takes_nothing_is_still_offered_as_an_object() -> None:
    # A tool with no arguments is a real case - the answer tool aside, a
    # retrieval call can legitimately take its defaults. Its schema still has
    # to be an object with an empty property set, because a schema that omitted
    # the shape entirely is not one the API accepts.
    no_properties: dict[str, Any] = {}
    nothing_required: list[str] = []

    Scenario() \
        .given(
            some_tool := a_tool_definition(properties=no_properties,
                                           required=nothing_required)
        ) \
        .when(
            lambda: to_tool(some_tool)
        ) \
        .then(
            all_of(
                _the_schema_describes_an_object(),
                _the_schema_offers(no_properties),
                _the_schema_requires(nothing_required)
            )
        )


def _the_offer_names(name: str) -> Assertion[ToolParam]:
    """The name the model calls, and the dispatcher looks up."""
    def assertion(offer: ToolParam) -> bool:
        if offer.get(NAME_KEY) != name:
            raise AssertionError(
                f"Expected the offer to name [{name}], got [{offer.get(NAME_KEY)}]."
            )

        return True

    return assertion


def _the_offer_describes_it_as(description: str) -> Assertion[ToolParam]:
    """What tells the model when to reach for this tool rather than another."""
    def assertion(offer: ToolParam) -> bool:
        if offer.get(DESCRIPTION_KEY) != description:
            raise AssertionError(
                f"Expected the offer to describe it as [{description}], "
                f"got [{offer.get(DESCRIPTION_KEY)}]."
            )

        return True

    return assertion


def _the_schema_of(offer: ToolParam) -> dict[str, Any]:
    """The offer's input schema, as the plain mapping it is."""
    schema: Any = offer.get(INPUT_SCHEMA_KEY, {})

    return dict(schema)


def _the_schema_offers(properties: dict[str, Any]) -> Assertion[ToolParam]:
    """The arguments the model may name."""
    def assertion(offer: ToolParam) -> bool:
        offered = _the_schema_of(offer).get(PROPERTIES_KEY)
        if offered != properties:
            raise AssertionError(
                f"Expected the schema to offer {properties}, got {offered}."
            )

        return True

    return assertion


def _the_schema_requires(required: list[str]) -> Assertion[ToolParam]:
    """The arguments the model may not leave out."""
    def assertion(offer: ToolParam) -> bool:
        demanded = _the_schema_of(offer).get(REQUIRED_KEY)
        if demanded != required:
            raise AssertionError(
                f"Expected the schema to require {required}, got {demanded}."
            )

        return True

    return assertion


def _the_offer_is_strict() -> Assertion[ToolParam]:
    """The flag that makes the model's arguments match the schema exactly."""
    def assertion(offer: ToolParam) -> bool:
        if offer.get(STRICT_KEY) is not True:
            raise AssertionError(
                f"Expected the offer to be strict, got [{offer.get(STRICT_KEY)}]."
            )

        return True

    return assertion


def _the_schema_forbids_anything_else() -> Assertion[ToolParam]:
    """The other half of strictness, and the half that is easy to forget."""
    def assertion(offer: ToolParam) -> bool:
        forbids = _the_schema_of(offer).get(ADDITIONAL_PROPERTIES_KEY)
        if forbids is not False:
            raise AssertionError(
                f"Expected the schema to forbid unlisted arguments, got [{forbids}]."
            )

        return True

    return assertion


def _every_nested_object_forbids_anything_else() -> Assertion[ToolParam]:
    """Strictness all the way down, not only at the top.

    The API refuses a schema whose nested objects are permissive, and it refuses
    the whole request rather than the one tool - so a tool carrying a nested
    object takes every other tool down with it, and reports an HTTP status
    rather than the omission.
    """
    def assertion(offer: ToolParam) -> bool:
        permissive = _objects_that_permit_anything(_the_schema_of(offer))
        if permissive:
            raise AssertionError(
                f"Expected every object in the schema to forbid unlisted "
                f"arguments, got {permissive} without it."
            )

        return True

    return assertion


def _objects_that_permit_anything(node: Any) -> list[Any]:
    """Every object anywhere in the schema that did not say `false`."""
    if isinstance(node, dict):
        found = [
            permissive
            for value in node.values()
            for permissive in _objects_that_permit_anything(value)
        ]

        if node.get(TYPE_KEY) == OBJECT_TYPE and node.get(
            ADDITIONAL_PROPERTIES_KEY
        ) is not False:
            found.append(node)

        return found

    if isinstance(node, list):
        return [
            permissive
            for value in node
            for permissive in _objects_that_permit_anything(value)
        ]

    return []


def _the_schema_describes_an_object() -> Assertion[ToolParam]:
    """A tool's arguments are always a named set, never a bare value."""
    def assertion(offer: ToolParam) -> bool:
        described = _the_schema_of(offer).get(TYPE_KEY)
        if described != OBJECT_TYPE:
            raise AssertionError(
                f"Expected the schema to describe an [{OBJECT_TYPE}], got [{described}]."
            )

        return True

    return assertion


def _the_definition_still_reads(tool: ToolDefinition,
                                properties: dict[str, Any]) -> Assertion[ToolParam]:
    """That rendering an offer left the definition it was rendered from alone."""
    def assertion(_: ToolParam) -> bool:
        if tool.properties != properties:
            raise AssertionError(
                f"Expected the definition to still read {properties}, got "
                f"{tool.properties}."
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
