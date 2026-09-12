from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario
from argus_web.views.prose import said_plainly

"""A model's sentence, said the way the rest of the page says things.

Every pattern under test here is a fact about how a language model happens to
write: which shapes it puts a flag's position in, that it sometimes breaks a
line around the arrow it drew, that it writes a time in the format the tools
speak. The repairs are presentation and change nothing that was claimed - which
is the line these draw, because the mistake in the other direction is a page
that quietly rewrites what the investigation said.

Each case is one sentence filled in twice: once as the model wrote it, once as
the page says it. The claim and the expectation are then visibly the same
sentence, and the only difference between them is the repair being tested - so
a repair that reached one word further shows up as a difference rather than
hiding inside a second string somebody typed out by hand.

A flag name is hyphenated in every one of these because that is what the repair
keys on: a state is a position only where it follows a flag's name, and "off"
anywhere else is English.
"""


@pytest.mark.unit
def test_a_flag_state_is_said_the_way_the_rest_of_the_page_says_it() -> None:
    # The model writes a flag's position as an ordinary lower-case word; every
    # other place it appears - the flag table, the action line - says ON and
    # OFF. Three spellings of one fact on one screen is a reader wondering
    # whether they are three facts.
    #
    # Which position it is does not matter, only that it is one. The flag name
    # is hyphenated because that is what the repair keys on: a state is a
    # position where it follows a flag's name, and "off" anywhere else is
    # English.
    some_lower_case_state = "off"
    some_claim_stating_a_flags_position = (
        f"The ramp turned some-ramped-flag {some_lower_case_state} and left it there."
    )

    Scenario() \
        .given(some_claim_stating_a_flags_position) \
        .when(lambda: said_plainly(some_claim_stating_a_flags_position)) \
        .then(_it_reads(
            f"The ramp turned some-ramped-flag {some_lower_case_state.upper()} and left it there."
        ))


@pytest.mark.unit
def test_a_quoted_state_is_said_the_same_way_and_loses_its_quotes() -> None:
    # The shape the model reaches for when it is being careful. Its quotes were
    # a way of marking the word as a value rather than prose; the page marks it
    # by shouting it, and doing both would mark it twice.
    some_lower_case_state = "off"
    some_claim_quoting_a_flags_position = (
        f"The ramp left some-ramped-flag '{some_lower_case_state}' for the hour."
    )

    Scenario() \
        .given(some_claim_quoting_a_flags_position) \
        .when(lambda: said_plainly(some_claim_quoting_a_flags_position)) \
        .then(_it_reads(
            f"The ramp left some-ramped-flag "
            f"{some_lower_case_state.upper()} for the hour."
        ))


@pytest.mark.unit
def test_a_word_that_is_merely_the_word_off_is_left_alone() -> None:
    # The other direction, and the more embarrassing mistake: a page that
    # uppercased every "off" in a sentence would be shouting at English. The
    # expectation is the claim itself, because nothing about it should change.
    Scenario() \
        .given(
            claim_using_off_as_english :=
                "The account page went off the rails when the ramp completed."
        ) \
        .when(lambda: said_plainly(claim_using_off_as_english)) \
        .then(_it_reads(claim_using_off_as_english))


@pytest.mark.unit
def test_a_claim_broken_across_lines_is_read_as_the_sentence_it_is() -> None:
    # The page lays out its own text. A line break arriving inside a claim is
    # typesetting the model did not mean and this page did not ask for, so it
    # becomes the space it stands for.
    #
    # Whatever whitespace came with the break goes with it: the model indents
    # its continuation and the page has no use for the indent either.
    some_break_the_model_wrote = "\n   "
    the_space_it_stands_for = " "
    some_claim_broken_mid_sentence = (
        f"The error rate rose{some_break_the_model_wrote}to 33% within a minute."
    )

    Scenario() \
        .given(some_claim_broken_mid_sentence) \
        .when(lambda: said_plainly(some_claim_broken_mid_sentence)) \
        .then(_it_reads(
            f"The error rate rose{the_space_it_stands_for}to 33% within a minute."
        ))


@pytest.mark.unit
def test_a_wire_format_instant_inside_a_sentence_is_said_as_a_clock_says_it() -> None:
    # The wire format is what the tools speak to each other. Every other time on
    # the page is a clock time, and one sentence in the wire format reads as a
    # different kind of fact from the table beside it.
    #
    # Which instant it is does not matter. What the expectation must not do is
    # state the clock time independently: sliced out of the instant, the two
    # cannot drift, and the slice is honest because the instant is already UTC
    # and the rendering only changes the format.
    some_instant = "2026-08-30T10:14:00Z"
    the_minute_it_reads_as = some_instant[11:16]
    some_claim_naming_a_wire_format_instant = f"The error rate rose at {some_instant}."

    Scenario() \
        .given(some_claim_naming_a_wire_format_instant) \
        .when(lambda: said_plainly(some_claim_naming_a_wire_format_instant)) \
        .then(_it_reads(f"The error rate rose at {the_minute_it_reads_as}."))


@pytest.mark.unit
def test_a_clock_time_carrying_a_zone_loses_only_the_zone() -> None:
    # A bare `10:14Z` is a wire-format time with its date left off, which
    # nothing can parse into an instant - so it is trimmed rather than parsed.
    # Parsing would need a date, and the only date available would be a guess.
    some_clock_time = "10:14"
    the_zone_the_model_wrote = "Z"
    some_claim_naming_a_zoned_clock_time = (
        f"The last good minute was {some_clock_time}{the_zone_the_model_wrote}."
    )

    Scenario() \
        .given(some_claim_naming_a_zoned_clock_time) \
        .when(lambda: said_plainly(some_claim_naming_a_zoned_clock_time)) \
        .then(_it_reads(f"The last good minute was {some_clock_time}."))


def _it_reads(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"expected [{expected}], got [{said}]")

        return True

    return assertion
