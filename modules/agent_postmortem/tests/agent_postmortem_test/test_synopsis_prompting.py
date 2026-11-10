"""What the model is asked for the executive synopsis's overview, and the one
shape its answer may take.

The model is handed the finished postmortem's figures by name and writes the
names where the figures go; code writes them in. Pay goes by name alone: the
request reaches the model's provider and its recording is committed, and the
model needs only where the figure goes.
"""

from __future__ import annotations

import pytest
from agent_postmortem.synopsis_prompting import (
    LIKELY_ONLY_WHERE_THE_CAUSE_SAYS,
    NO_SIZE_IN_WORDS,
    NOTHING_BEYOND_THE_LIST,
    NOTHING_LASTED,
    OVERVIEW_FIELD,
    OVERVIEW_TOOL_NAME,
    SPEAK_OF_ARGUS_BY_NAME,
    SUBMIT_EXECUTIVE_OVERVIEW,
    WHICH_ONES_WERE_AFFECTED,
    Paging,
    overview_ask,
    paging_of,
    required_figures,
    synopsis_policy,
)
from argus_core.models import Ask, Effort, ModelPolicy, Transcript
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

DONT_CARE_CURRENCY = "USD"
# What the responders' minutes were worth, which the ask may name and never show.
SOME_PAY = "31.50"
SOME_FIGURES = {"duration": "7m 12s",
                "customer_loss": f"1,840.01 {DONT_CARE_CURRENCY}",
                "responders": "3",
                "responder_cost": f"{SOME_PAY} {DONT_CARE_CURRENCY}"}
SOME_DURATION_ALONE = {"duration": SOME_FIGURES["duration"]}
SOME_SYMPTOM = "Checkout failed"
SOME_CAUSE = "A flag change turned off the path checkout relies on."
SOME_RESOLUTION = ("Argus: turned monthly-spend-feature off - recovered",
                   "Argus: proposed a fix, PR #7 - opened as a draft")


@pytest.mark.unit
def test_each_figure_is_shown_with_its_name_after_it() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(all_of(
            _says(_shown("duration")),
            _says(_shown("customer_loss")),
            _says(_shown("responders"))
        ))


@pytest.mark.unit
def test_the_loss_is_shown_as_argus_s_estimate() -> None:
    # Shown as "(estimated)" alone, 4 overviews in 10 said "We estimate".
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(
            _says(f"What it cost the shop in takings (estimated by Argus): "
                  f"{_shown('customer_loss')}")
        )


@pytest.mark.unit
def test_pay_is_named_and_never_shown() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(all_of(
            _says("{responder_cost}"),
            _never_says(SOME_PAY)
        ))


@pytest.mark.unit
def test_the_figures_the_record_holds_are_required() -> None:
    # The duration, the loss and the cost, where each was measured - and not
    # the people or their minutes, which an overview may leave to the table.
    Scenario() \
        .when(
            lambda: required_figures(SOME_FIGURES)
        ) \
        .then(
            the_answer_was(("duration", "customer_loss", "responder_cost"))
        )


@pytest.mark.unit
def test_a_figure_the_record_lacks_is_not_required() -> None:
    some_figures_with_no_duration_or_loss = {name: SOME_FIGURES[name]
                                             for name in ("responders", "responder_cost")}

    Scenario() \
        .when(
            lambda: required_figures(some_figures_with_no_duration_or_loss)
        ) \
        .then(
            the_answer_was(("responder_cost",))
        )


@pytest.mark.unit
def test_the_ask_says_which_figures_must_be_named() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_DURATION_ALONE)
        ) \
        .then(
            _says("Name {duration} in your overview.")
        )


@pytest.mark.unit
def test_what_happened_and_what_was_done_are_handed_over_as_written() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(all_of(
            _says(SOME_SYMPTOM),
            _says(SOME_CAUSE),
            *(_says(line) for line in SOME_RESOLUTION)
        ))


@pytest.mark.unit
def test_the_ask_forbids_claims_beyond_the_list_and_sizes_said_in_words() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(all_of(
            _says(NOTHING_BEYOND_THE_LIST),
            _says(NO_SIZE_IN_WORDS),
            _says(f"Call {OVERVIEW_TOOL_NAME} with your overview.")
        ))


@pytest.mark.unit
def test_the_ask_has_argus_spoken_of_by_name_never_as_we() -> None:
    # Both first answers said "we": once crediting a team, once speaking for a
    # company that had said nothing.
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(
            _says(SPEAK_OF_ARGUS_BY_NAME)
        )


@pytest.mark.unit
def test_the_ask_has_the_affected_said_by_which_ones_not_how_many() -> None:
    # Barred from "many", one answer said "shoppers" - every one of them -
    # where the cause says which.
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(
            _says(WHICH_ONES_WERE_AFFECTED)
        )


@pytest.mark.unit
def test_the_ask_keeps_likely_on_what_the_cause_says_is_likely() -> None:
    # One answer moved the cause's "likely" onto the trigger the revert had
    # confirmed, and said the unrun reading flat.
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(
            _says(LIKELY_ONLY_WHERE_THE_CAUSE_SAYS)
        )


@pytest.mark.unit
@pytest.mark.parametrize("paging, said", [
    (Paging.NOT_PAGED, "- Nobody was paged: no on-call incident was linked to this one."),
    (Paging.UNACKNOWLEDGED, "- Somebody was paged, and nobody acknowledged the page.")
], ids=["nobody-paged", "page-unacknowledged"])
def test_where_nobody_responded_the_ask_says_why_among_the_figures(paging: Paging,
                                                                   said: str) -> None:
    # Asked what it cost the people who responded and handed no figure for
    # them, the model has nothing true to say it from but this - and a page
    # nobody acknowledged is no page never sent.
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_DURATION_ALONE, paging=paging)
        ) \
        .then(
            _says(f"Figures:\n- How long it lasted: {_shown('duration')}\n{said}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("paging", [Paging.ANSWERED, Paging.NOT_KNOWN],
                         ids=["answered", "not-known"])
def test_where_somebody_responded_or_nobody_can_say_the_ask_says_nothing_of_paging(
        paging: Paging) -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES, paging=paging)
        ) \
        .then(all_of(
            _never_says("Nobody was paged"),
            _never_says("Somebody was paged")
        ))


@pytest.mark.unit
def test_where_the_alarm_was_disproven_the_ask_says_so_first_among_the_figures() -> None:
    # Asked how long it lasted and handed no duration, an overview said the
    # record did not say how long the alarm stayed active - beside a synopsis
    # saying when it was raised and when it was disproven.
    no_figures: dict[str, str] = {}

    Scenario() \
        .when(
            lambda: _an_ask(figures=no_figures, disproven=True)
        ) \
        .then(
            _says(f"Figures:\n{NOTHING_LASTED}")
        )


@pytest.mark.unit
def test_where_the_alarm_was_not_disproven_the_ask_says_nothing_of_it() -> None:
    Scenario() \
        .when(
            lambda: _an_ask(figures=SOME_FIGURES)
        ) \
        .then(
            _never_says(NOTHING_LASTED)
        )


@pytest.mark.unit
@pytest.mark.parametrize("paged, responders, expected", [
    (True, 2, Paging.ANSWERED),
    (True, 0, Paging.UNACKNOWLEDGED),
    (False, 0, Paging.NOT_PAGED),
    (None, None, Paging.NOT_KNOWN),
    (None, 0, Paging.NOT_KNOWN)
], ids=["answered", "page-unacknowledged", "nobody-paged", "source-unread",
        "zero-with-paging-unknown"])
def test_the_paging_is_read_off_whether_a_page_went_out_and_who_answered_it(
        paged: bool | None, responders: int | None, expected: Paging) -> None:
    # Zero responders alone says neither: a page nobody acknowledged and no
    # page at all both count nobody.
    Scenario() \
        .when(
            lambda: paging_of(paged, responders)
        ) \
        .then(
            the_answer_was(expected)
        )


@pytest.mark.unit
def test_the_tool_takes_one_required_overview() -> None:
    Scenario() \
        .when(
            lambda: (SUBMIT_EXECUTIVE_OVERVIEW.name, SUBMIT_EXECUTIVE_OVERVIEW.required)
        ) \
        .then(
            the_answer_was((OVERVIEW_TOOL_NAME, [OVERVIEW_FIELD]))
        )


@pytest.mark.unit
def test_the_overview_is_asked_under_no_brief_of_the_postmortem_s() -> None:
    # Everything the overview needs is in its one message. The postmortem's
    # brief is about five whys and a causal chain, and sent as this call's
    # system it would ask for a tool this call does not offer.
    some_model = "some-model"
    some_effort: Effort = "low"

    Scenario() \
        .when(
            lambda: synopsis_policy(some_model, some_effort)
        ) \
        .then(
            the_answer_was(ModelPolicy(model=some_model, effort=some_effort, brief="",
                                       one_tool_call_per_turn=True))
        )


def _an_ask(figures: dict[str, str],
            paging: Paging = Paging.ANSWERED,
            disproven: bool = False) -> Transcript:
    return overview_ask(service="io-shop",
                        symptom=SOME_SYMPTOM,
                        cause=SOME_CAUSE,
                        figures=figures,
                        paging=paging,
                        disproven=disproven,
                        resolution=SOME_RESOLUTION)


def _shown(name: str) -> str:
    """A figure of `SOME_FIGURES` as the ask shows it: its value, then its name."""
    return f"{SOME_FIGURES[name]} {{{name}}}"


def _says(expected: str) -> Assertion[Transcript]:
    def assertion(asked: Transcript) -> bool:
        text = _the_text_of(asked)
        if expected not in text:
            raise AssertionError(f"Expected the ask to say [{expected}], and it says:\n{text}")

        return True

    return assertion


def _never_says(unexpected: str) -> Assertion[Transcript]:
    def assertion(asked: Transcript) -> bool:
        text = _the_text_of(asked)
        if unexpected in text:
            raise AssertionError(
                f"Expected the ask never to say [{unexpected}], and it says:\n{text}")

        return True

    return assertion


def _the_text_of(asked: Transcript) -> str:
    return "\n".join(entry.text for entry in asked if isinstance(entry, Ask))
