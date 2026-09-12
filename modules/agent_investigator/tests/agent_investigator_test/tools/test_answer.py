"""The one schema Argus writes by hand, and the whole of what an answer may say.

Nothing downstream can read a field the model was never asked for, so the names
here are the names a `Hypothesis` is built from - and a drift between the two
does not fail anything: every hypothesis simply arrives with the field unset,
and the page quietly stops saying something it used to say. This is where that
agreement is pinned. The loop's own tests build answers through a builder and
deliberately no longer spell the wire keys out.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from agent_investigator.tools.answer import HYPOTHESES_ARG, answer_tool
from argus_core.models.tool_definition import ToolDefinition
from argus_testkit import Assertion, Scenario, all_of

type _Part = Callable[[ToolDefinition], dict[str, Any]]


@pytest.mark.unit
def test_an_explanation_asks_for_every_field_a_hypothesis_is_built_from() -> None:
    built_from = {
        "summary",
        "cause_type",
        "confidence",
        "supporting_evidence",
        "subject",
        "from_state",
        "to_state"
    }

    Scenario() \
        .when(
            lambda: answer_tool()
        ) \
        .then(
            all_of(
                _offers(built_from, _an_explanation, "an explanation"),
                _requires(built_from, _an_explanation, "an explanation")
            )
        )


@pytest.mark.unit
def test_a_cited_fact_asks_for_its_claim_and_the_moment_it_happened() -> None:
    # The instant is required rather than optional: a model that omitted it
    # would be read as having considered the question and found no moment,
    # which is a different answer from never having been asked.
    cited_as = {"claim", "at"}

    Scenario() \
        .when(
            lambda: answer_tool()
        ) \
        .then(
            all_of(
                _offers(cited_as, _a_cited_fact, "a cited fact"),
                _requires(cited_as, _a_cited_fact, "a cited fact")
            )
        )


def _an_explanation(tool: ToolDefinition) -> dict[str, Any]:
    """One entry of the ranked list, as the model is asked to fill it in."""
    explanation: dict[str, Any] = tool.properties[HYPOTHESES_ARG]["items"]

    return explanation


def _a_cited_fact(tool: ToolDefinition) -> dict[str, Any]:
    """One piece of supporting evidence, as it hangs off an explanation."""
    cited: dict[str, Any] = _an_explanation(tool)["properties"]["supporting_evidence"]["items"]

    return cited


def _offers(names: set[str], part: _Part, called: str) -> Assertion[ToolDefinition]:
    """Exactly these fields and no others.

    Exactly rather than at least: a strict schema refuses an argument it did
    not declare, so a field nothing offers is one the model cannot send however
    plainly the description asks for it.
    """
    def assertion(tool: ToolDefinition) -> bool:
        offered = set(part(tool)["properties"])
        if offered != names:
            raise AssertionError(
                f"Expected {called} to offer {sorted(names)}, got {sorted(offered)}."
            )

        return True

    return assertion


def _requires(names: set[str], part: _Part, called: str) -> Assertion[ToolDefinition]:
    """Every one of them required, including the nullable ones.

    A nullable field that is merely offered can be left out, and an omission
    and a stated null are different answers: one says the model considered the
    question, the other says nothing at all.
    """
    def assertion(tool: ToolDefinition) -> bool:
        required = set(part(tool)["required"])
        if required != names:
            raise AssertionError(
                f"Expected {called} to require {sorted(names)}, got {sorted(required)}."
            )

        return True

    return assertion
