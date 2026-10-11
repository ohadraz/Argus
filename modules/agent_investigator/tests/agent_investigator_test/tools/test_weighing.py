"""How the model says where a lead stands, and the whole of what it may say.

The loop reads a weighing off the call's own arguments, so the names here are
the names a `Weighing` is built from, and the standings offered are the
standings the kernel knows - a drift between the two fails nothing: every
weighing simply comes back refused. This is where that agreement is pinned.
The loop's own tests name the keys through these same constants, so a drift
would move them too, and they would not see it.
"""

from __future__ import annotations

import pytest
from agent_investigator.tools.weighing import (
    LEAD_ARG,
    REASON_ARG,
    STANDING_ARG,
    weigh_lead_tool,
)
from argus_core.models import Standing, ToolDefinition
from argus_testkit import Assertion, Scenario, all_of


@pytest.mark.unit
def test_a_weighing_asks_for_the_lead_its_standing_and_why() -> None:
    # Why is required rather than optional: the person who wrote the lead is
    # told it, and a standing with no reason is a verdict nobody can check.
    asked_for = {LEAD_ARG, STANDING_ARG, REASON_ARG}

    Scenario() \
        .when(lambda: weigh_lead_tool()) \
        .then(all_of(_offers(asked_for), _requires(asked_for)))


@pytest.mark.unit
def test_the_standings_offered_are_every_standing_there_is() -> None:
    # A standing the schema offered and the kernel does not know is refused on
    # every use; one the kernel knows and the schema leaves out is a verdict
    # the model can never give.
    Scenario() \
        .when(lambda: weigh_lead_tool()) \
        .then(_the_standings_offered_are({standing.value for standing in Standing}))


@pytest.mark.unit
def test_the_model_is_told_what_each_standing_allows() -> None:
    # The rule a lead is weighed by travels with the tool rather than in the
    # brief, so an incident nobody wrote about is sent the brief it always was.
    # Asserted as "every standing is described" rather than against wording.
    Scenario() \
        .when(lambda: weigh_lead_tool()) \
        .then(_every_standing_is_described())


def _offers(expected: set[str]) -> Assertion[ToolDefinition]:
    def assertion(definition: ToolDefinition) -> bool:
        if set(definition.properties) != expected:
            raise AssertionError(
                f"Expected a weighing to offer {sorted(expected)}, it offers "
                f"{sorted(definition.properties)}."
            )

        return True

    return assertion


def _requires(expected: set[str]) -> Assertion[ToolDefinition]:
    def assertion(definition: ToolDefinition) -> bool:
        if set(definition.required) != expected:
            raise AssertionError(
                f"Expected a weighing to require {sorted(expected)}, it requires "
                f"{sorted(definition.required)}."
            )

        return True

    return assertion


def _the_standings_offered_are(expected: set[str]) -> Assertion[ToolDefinition]:
    def assertion(definition: ToolDefinition) -> bool:
        offered = set(definition.properties[STANDING_ARG].get("enum", []))

        if offered != expected:
            raise AssertionError(
                f"Expected the standings offered to be {sorted(expected)}, got "
                f"{sorted(offered)}."
            )

        return True

    return assertion


def _every_standing_is_described() -> Assertion[ToolDefinition]:
    def assertion(definition: ToolDefinition) -> bool:
        missing = [standing.value for standing in Standing
                   if f"{standing.value}:" not in definition.description]

        if missing:
            raise AssertionError(
                f"Expected the tool to say what each standing allows, and it does not "
                f"describe {missing}: [{definition.description}]."
            )

        return True

    return assertion
