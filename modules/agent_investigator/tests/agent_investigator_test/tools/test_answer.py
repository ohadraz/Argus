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
from argus_core.models import FailureMode, ToolDefinition
from argus_testkit import Assertion, Scenario, all_of

type _Part = Callable[[ToolDefinition], dict[str, Any]]


@pytest.mark.unit
def test_an_explanation_asks_for_every_field_a_hypothesis_is_built_from() -> None:
    built_from = {
        "summary",
        "failure_mode",
        "confidence",
        "supporting_evidence",
        "subject",
        "from_state",
        "to_state",
        "faulting_service"
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


@pytest.mark.unit
def test_the_model_is_told_what_each_cause_means_and_not_only_its_name() -> None:
    # A bare enum asks the model to infer a taxonomy from seven hyphenated
    # strings, and the two that are hardest to tell apart are exactly the two
    # that dispatch to different mitigations: a bad deployment ships new code
    # and a config-induced failure ships a bad value with code nobody touched.
    # Handed only the names, a model that has just seen a deploy land at the
    # onset picks the deployment - and it is not obviously wrong, because
    # nothing ever told it what the other one was for.
    #
    # Asserted as "every mode is described" rather than against particular
    # wording, because the wording is the prompt's to tune and the property is
    # that no cause reaches the model as a name alone.
    Scenario() \
        .when(
            lambda: answer_tool()
        ) \
        .then(
            _every_cause_is_explained()
        )


@pytest.mark.unit
def test_the_field_that_names_a_service_says_when_it_has_to_be_filled_in() -> None:
    # Offering the field is not the same as asking for it. Every other nullable
    # field here is null for most answers and that is fine - a flag toggle names
    # no versions, a leak names no flag - but this one is what a restart is
    # addressed to, and an internal dependency's failure with it left null is a
    # diagnosis nothing can act on. So the description has to say so by naming
    # the mode, in the way the causes themselves are described rather than merely
    # listed.
    Scenario() \
        .when(
            lambda: answer_tool()
        ) \
        .then(
            _the_field("faulting_service").says_it_is_needed_for(
                FailureMode.INTERNAL_DEPENDENCY_FAILURE
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


def _every_cause_is_explained() -> Assertion[ToolDefinition]:
    def assertion(tool: ToolDefinition) -> bool:
        described = _an_explanation(tool)["properties"]["failure_mode"]["description"]
        unexplained = [
            cause.value for cause in FailureMode if cause.value not in described
        ]

        if unexplained:
            raise AssertionError(
                f"The model is offered {sorted(unexplained)} as bare names: the "
                f"field's description never says what they mean, so telling them "
                f"apart is guesswork from the spelling."
            )

        return True

    return assertion


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


def _the_field(name: str) -> _Field:
    """One field of an explanation, named so the call site reads as a sentence.

    A factory rather than a lowercase class. The sentence is the point -
    `_the_field("faulting_service").says_it_is_needed_for(...)` - and a class
    spelled to make it work is a class named against the convention, which
    costs a suppression on every linter that has ever been asked about it.
    """
    return _Field(name)


class _Field:
    """Assertions about one field of an explanation.

    A class rather than loose functions taking the name again, for the reason
    `_the_meaning_of` is one in the kernel's own suite: the failure has to say
    which field fell short, and threading a name through every helper is how it
    comes to be left out of one of them.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def says_it_is_needed_for(self, cause: FailureMode) -> Assertion[ToolDefinition]:
        def assertion(tool: ToolDefinition) -> bool:
            described = _an_explanation(tool)["properties"][self._name]["description"]

            if cause.value not in described:
                raise AssertionError(
                    f"The description of [{self._name}] never mentions "
                    f"[{cause.value}], so nothing tells the model that an answer "
                    f"of that mode without this field is one nothing can act on."
                )

            return True

        return assertion
