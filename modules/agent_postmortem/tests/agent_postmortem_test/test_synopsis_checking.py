"""What is wrong with an overview, said in words the model can act on.

The postmortem's figure rules, run by the same code, and the synopsis's own:
the figures the record holds that the overview has to name, and Argus said by
name rather than as "we". Each fault comes back under the rule that found it,
so a fault is sent back once per rule.
"""

from __future__ import annotations

import pytest
from agent_postmortem.synopsis_checking import overview_faults
from argus_testkit import Assertion, Scenario

# The figures' names as the synopsis knows them: the overview has to name the
# duration, the loss and the response's cost wherever the record holds them.
DURATION = "duration"
CUSTOMER_LOSS = "customer_loss"
RESPONDERS = "responders"
RESPONDER_COST = "responder_cost"

SOME_FIGURES = {DURATION: "7m 12s", CUSTOMER_LOSS: "1,840.01 USD",
                RESPONDERS: "3", RESPONDER_COST: "31.50 USD"}

AN_OVERVIEW_NAMING_ALL = (
    f"Checkout failed for {{{DURATION}}} after a flag change, costing the shop "
    f"{{{CUSTOMER_LOSS}}} in takings; {{{RESPONDERS}}} engineers responded, at "
    f"{{{RESPONDER_COST}}}. Argus turned the flag off and opened a draft fix for review."
)


@pytest.mark.unit
def test_an_overview_naming_what_it_must_and_writing_no_figure_is_kept() -> None:
    Scenario() \
        .when(
            lambda: overview_faults(AN_OVERVIEW_NAMING_ALL, SOME_FIGURES)
        ) \
        .then(
            _refused_by_exactly([])
        )


@pytest.mark.unit
def test_a_figure_the_overview_writes_itself_is_refused_by_the_postmortems_rule() -> None:
    some_number = 7

    Scenario() \
        .when(
            lambda: overview_faults(
                AN_OVERVIEW_NAMING_ALL.replace(
                    f"for {_named(DURATION)}",
                    f"for {_named(DURATION)}, {some_number} minutes,"),
                SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("numbers_in_digits", f"[{some_number}]")
        )


@pytest.mark.unit
def test_a_required_figure_left_unnamed_is_refused() -> None:
    # Asked to write it, a summary once left out how long the incident ran.
    Scenario() \
        .when(
            lambda: overview_faults(AN_OVERVIEW_NAMING_ALL.replace(f" for {_named(DURATION)}", ""),
                                    SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("figures_left_unnamed", f"[{_named(DURATION)}]")
        )


@pytest.mark.unit
def test_a_figure_the_record_lacks_is_not_required() -> None:
    # A disproven alarm has no loss and no duration to name.
    some_figures_of_a_false_alarm = {RESPONDERS: "1", RESPONDER_COST: "4.10 USD"}

    Scenario() \
        .when(
            lambda: overview_faults(f"The alarm was false; {_named(RESPONDERS)} engineers "
                                    f"looked, at {_named(RESPONDER_COST)}.",
                                    some_figures_of_a_false_alarm)
        ) \
        .then(
            _refused_by_exactly([])
        )


@pytest.mark.unit
def test_a_name_no_figure_has_is_refused() -> None:
    some_name_no_figure_has = _named("peak")

    Scenario() \
        .when(
            lambda: overview_faults(
                f"{AN_OVERVIEW_NAMING_ALL} Requests failed at {some_name_no_figure_has}.",
                SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("figures_nobody_gave", f"[{some_name_no_figure_has}]")
        )


@pytest.mark.unit
def test_an_empty_overview_is_refused() -> None:
    Scenario() \
        .when(
            lambda: overview_faults("  ", {})
        ) \
        .then(
            _refused_by_quoting("an_empty_overview", "empty")
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence_around, word", [
    (f"WORD estimate the shop lost {{{CUSTOMER_LOSS}}}.", "We"),
    (f"The shop lost {{{CUSTOMER_LOSS}}}, WORD estimate.", "we"),
    ("WORD've confirmed the change worked.", "We"),
    (f"WORD estimate is {{{CUSTOMER_LOSS}}}.", "Our"),
    (f"The flag cost WORD {{{CUSTOMER_LOSS}}}.", "us")
], ids=["we-opening", "we", "we-contracted", "our", "us"])
def test_an_overview_speaking_as_we_is_refused(sentence_around: str, word: str) -> None:
    # Argus is the system that responded; "we" credits a team with what it
    # did, or speaks for a company that said nothing.
    sentence = sentence_around.replace("WORD", word)

    Scenario() \
        .when(
            lambda: overview_faults(f"{AN_OVERVIEW_NAMING_ALL} {sentence}", SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("speaking_as_we", f"[{word}]")
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    "Argus used a flag to stop it.",
    "The loss is in US dollars.",
    "Users were affected, as were their sessions."
], ids=["argus-and-used", "us-dollars", "users"])
def test_a_word_merely_containing_we_or_us_is_not_refused(sentence: str) -> None:
    Scenario() \
        .when(
            lambda: overview_faults(f"{AN_OVERVIEW_NAMING_ALL} {sentence}", SOME_FIGURES)
        ) \
        .then(
            _refused_by_exactly([])
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    'Dana Kuki resolved it, saying "rolled the flag back by hand, we\'re fine".',
    "Dana Kuki resolved it, saying “rolled the flag back by hand, we’re fine”."
], ids=["straight-quotes", "curly-quotes"])
def test_we_inside_a_person_s_quoted_words_is_not_refused(sentence: str) -> None:
    # The Resolution list quotes the person who ended it; their "we" is
    # theirs, not Argus speaking as one.
    Scenario() \
        .when(
            lambda: overview_faults(f"{AN_OVERVIEW_NAMING_ALL} {sentence}", SOME_FIGURES)
        ) \
        .then(
            _refused_by_exactly([])
        )


@pytest.mark.unit
def test_we_outside_the_quoted_words_is_still_refused() -> None:
    some_word_as_we = "We"

    Scenario() \
        .when(
            lambda: overview_faults(
                f'{AN_OVERVIEW_NAMING_ALL} {some_word_as_we} heard Dana say "all good".',
                SOME_FIGURES)
        ) \
        .then(
            _refused_by_quoting("speaking_as_we", f"[{some_word_as_we}]")
        )


def _named(figure: str) -> str:
    """A figure's name as an overview writes it, braces and all."""
    return f"{{{figure}}}"


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
            raise AssertionError(f"Expected the rules {rules} to refuse it, got {faults}.")

        return True

    return assertion
