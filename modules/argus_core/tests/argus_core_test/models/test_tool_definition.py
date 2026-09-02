from __future__ import annotations

from typing import Any, Final

import pytest
from argus_core.models.tool_definition import ToolDefinition
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from pydantic import ValidationError

"""What Argus offers the model, and the wire shape that offer takes.

The counterpart to `test_turn.py`: that file covers a reply coming back, this
one covers the tools going out. Offline for the same reason - what is under
test is the translation, not the call.

A tool is described in Argus's own terms and rendered into Anthropic's only at
the edge. The rendering is where the strictness rules live, and they are the
whole reason this is a type rather than a dict written out at each call site:
a schema that forgets `additionalProperties` silently stops being strict, and
nothing downstream notices until the model sends an argument nobody handles.
"""


# Anthropic's own vocabulary for a tool offer. Stated here rather than imported
# from the code under test: a test that borrowed Argus's spelling would agree
# with it even when both are wrong.
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
            lambda: some_tool.to_wire()
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
            lambda: some_tool.to_wire()
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
            lambda: some_tool.to_wire()
        ) \
        .then(
            all_of(
                _the_offer_is_strict(),
                _the_schema_forbids_anything_else(),
                _the_schema_describes_an_object()
            )
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
            lambda: some_tool.to_wire()
        ) \
        .then(
            all_of(
                _the_schema_describes_an_object(),
                _the_schema_offers(no_properties),
                _the_schema_requires(nothing_required)
            )
        )


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


def _the_offer_names(name: str) -> Assertion[dict[str, Any]]:
    """The name the model calls, and the dispatcher looks up."""
    def assertion(offer: dict[str, Any]) -> bool:
        if offer.get(NAME_KEY) != name:
            raise AssertionError(
                f"Expected the offer to name [{name}], got [{offer.get(NAME_KEY)}]."
            )

        return True

    return assertion


def _the_offer_describes_it_as(description: str) -> Assertion[dict[str, Any]]:
    """What tells the model when to reach for this tool rather than another."""
    def assertion(offer: dict[str, Any]) -> bool:
        if offer.get(DESCRIPTION_KEY) != description:
            raise AssertionError(
                f"Expected the offer to describe it as [{description}], "
                f"got [{offer.get(DESCRIPTION_KEY)}]."
            )

        return True

    return assertion


def _the_schema_offers(properties: dict[str, Any]) -> Assertion[dict[str, Any]]:
    """The arguments the model may name."""
    def assertion(offer: dict[str, Any]) -> bool:
        offered = offer.get(INPUT_SCHEMA_KEY, {}).get(PROPERTIES_KEY)
        if offered != properties:
            raise AssertionError(
                f"Expected the schema to offer {properties}, got {offered}."
            )

        return True

    return assertion


def _the_schema_requires(required: list[str]) -> Assertion[dict[str, Any]]:
    """The arguments the model may not leave out."""
    def assertion(offer: dict[str, Any]) -> bool:
        demanded = offer.get(INPUT_SCHEMA_KEY, {}).get(REQUIRED_KEY)
        if demanded != required:
            raise AssertionError(
                f"Expected the schema to require {required}, got {demanded}."
            )

        return True

    return assertion


def _the_offer_is_strict() -> Assertion[dict[str, Any]]:
    """The flag that makes the model's arguments match the schema exactly."""
    def assertion(offer: dict[str, Any]) -> bool:
        if offer.get(STRICT_KEY) is not True:
            raise AssertionError(
                f"Expected the offer to be strict, got [{offer.get(STRICT_KEY)}]."
            )

        return True

    return assertion


def _the_schema_forbids_anything_else() -> Assertion[dict[str, Any]]:
    """The other half of strictness, and the half that is easy to forget."""
    def assertion(offer: dict[str, Any]) -> bool:
        forbids = offer.get(INPUT_SCHEMA_KEY, {}).get(ADDITIONAL_PROPERTIES_KEY)
        if forbids is not False:
            raise AssertionError(
                f"Expected the schema to forbid unlisted arguments, got [{forbids}]."
            )

        return True

    return assertion


def _the_schema_describes_an_object() -> Assertion[dict[str, Any]]:
    """A tool's arguments are always a named set, never a bare value."""
    def assertion(offer: dict[str, Any]) -> bool:
        described = offer.get(INPUT_SCHEMA_KEY, {}).get(TYPE_KEY)
        if described != OBJECT_TYPE:
            raise AssertionError(
                f"Expected the schema to describe an [{OBJECT_TYPE}], got [{described}]."
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
