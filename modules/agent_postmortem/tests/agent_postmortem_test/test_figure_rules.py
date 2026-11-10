"""The rules that refuse a figure prose writes itself, over any sentences.

The postmortem's checks run them over its answer; the executive synopsis runs
them over its overview. Each rule's faults come back under that rule's own
name, because a fault is sent back once per rule: one merged rule would keep a
second answer that a different rule would refuse.
"""

from __future__ import annotations

import pytest
from agent_postmortem.figure_rules import figure_faults
from agent_postmortem.figures import Figure
from argus_testkit import Assertion, Scenario

SOME_FIGURE_NAME = "duration"
SOME_FIGURE_SAID = "7 min 12 s"
SOME_FIGURES = {SOME_FIGURE_NAME: Figure(given=SOME_FIGURE_SAID, written=SOME_FIGURE_SAID)}

# For the sentences that name no figure: only a name is read against these.
DONT_CARE_FIGURES: dict[str, Figure] = {}

SOME_REVISION = "1234567890abcdef"


@pytest.mark.unit
def test_a_figure_in_digits_is_refused_by_its_rule() -> None:
    some_number = 7

    Scenario() \
        .when(
            lambda: figure_faults([f"Checkout failed for {some_number} minutes."],
                                  DONT_CARE_FIGURES)
        ) \
        .then(
            _refused_by_quoting("numbers_in_digits", f"[{some_number}]")
        )


@pytest.mark.unit
def test_a_figure_spelled_out_is_refused_by_its_rule() -> None:
    some_figure_spelled_out = "one thousand two hundred"

    Scenario() \
        .when(
            lambda: figure_faults([f"The shop lost {some_figure_spelled_out} dollars."],
                                  DONT_CARE_FIGURES)
        ) \
        .then(
            _refused_by_quoting("figures_spelled_out", f"[{some_figure_spelled_out}]")
        )


@pytest.mark.unit
def test_a_figure_said_in_one_word_is_refused_by_its_rule() -> None:
    some_figure_in_a_word = "tripled"

    Scenario() \
        .when(
            lambda: figure_faults([f"Errors {some_figure_in_a_word} while it was broken."],
                                  DONT_CARE_FIGURES)
        ) \
        .then(
            _refused_by_quoting("figures_said_in_a_word", f"[{some_figure_in_a_word}]")
        )


@pytest.mark.unit
def test_a_name_no_figure_has_is_refused_by_its_rule() -> None:
    some_name_no_figure_has = "{customer_loss}"

    Scenario() \
        .when(
            lambda: figure_faults([f"The shop lost {some_name_no_figure_has}."], SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("figures_nobody_gave", f"[{some_name_no_figure_has}]")
        )


@pytest.mark.unit
def test_two_rules_breaking_are_two_entries() -> None:
    Scenario() \
        .when(
            lambda: figure_faults(["It lasted 7 minutes and errors tripled."], DONT_CARE_FIGURES)
        ) \
        .then(
            _refused_by_exactly(["numbers_in_digits", "figures_said_in_a_word"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    f"Checkout failed for {{{SOME_FIGURE_NAME}}}.",
    "Most requests failed for several minutes.",
    "The fault is on line 47 of the pricing module.",
    f"Deploy {SOME_REVISION[:7]} set it off."
], ids=["a-figure-named", "a-size-without-a-number", "a-line-of-source", "a-revision-read"])
def test_what_names_or_describes_rather_than_measures_is_not_refused(sentence: str) -> None:
    Scenario() \
        .when(
            lambda: figure_faults([sentence], SOME_FIGURES,
                                  revisions=frozenset({SOME_REVISION}))
        ) \
        .then(
            _refused_by_exactly([])
        )


@pytest.mark.unit
def test_a_word_the_evidence_quotes_in_braces_is_not_refused() -> None:
    # A format string a diff quotes is the evidence's text, not a figure.
    some_quoted_word = "amount_cents"

    Scenario() \
        .when(
            lambda: figure_faults([f"It formats {{{some_quoted_word}}} wrongly."], SOME_FIGURES,
                                  quoted=frozenset({some_quoted_word}))
        ) \
        .then(
            _refused_by_exactly([])
        )


def _refused_by_quoting(rule: str, quoted: str) -> Assertion[dict[str, list[str]]]:
    def assertion(faults: dict[str, list[str]]) -> bool:
        if list(faults) != [rule] or not any(quoted in fault for fault in faults[rule]):
            raise AssertionError(
                f"Expected only the rule [{rule}] to refuse it, quoting {quoted}, "
                f"got {faults}.")

        return True

    return assertion


def _refused_by_exactly(rules: list[str]) -> Assertion[dict[str, list[str]]]:
    def assertion(faults: dict[str, list[str]]) -> bool:
        if sorted(faults) != sorted(rules):
            raise AssertionError(
                f"Expected the rules {rules} to refuse it, got {faults}.")

        return True

    return assertion
