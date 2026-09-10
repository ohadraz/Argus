from __future__ import annotations

import pytest
from argus_core.llm.escapes import with_escapes_resolved
from argus_testkit import Assertion, Scenario

"""What a model wrote, where it escaped a character instead of writing it.

The model's own artefact, not the API's: the SDK decodes a response exactly
once and correctly, so an escape sequence still standing in a decoded value is
one the model typed a backslash into. It arrives that way rarely - three times
across forty recorded answers - and always around typography it could have
written directly, an arrow or a dash.

Repaired here, where the answer is accepted, rather than in whichever view
happens to show it: the same summary reaches a web page, a postmortem and a
Slack message, and a repair living in one of them is absent from the other two.

Only `\\uXXXX` is resolved. Every other backslash sequence is left exactly as
written, because this runs over every tool argument of every agent - Code-Fix
proposes source code, and a `\\n` inside a code sample is two characters the
model meant.

Each case is one sentence filled in twice: once as the model wrote it, once as
it is accepted. Where nothing should change, the expectation is the sentence
itself, so a repair that reached further shows up as a difference rather than
hiding inside a second string somebody typed out by hand.
"""


@pytest.mark.unit
def test_an_escaped_character_is_accepted_as_the_character_it_names() -> None:
    # What the model actually sent, in a postmortem assumption that reached the
    # record: the dash between two times, written as its escape. Shown as it
    # arrived, a reader gets six characters of machinery in the middle of a
    # sentence about when the incident ran.
    the_character_it_names = "–"
    some_escape_the_model_wrote = "\\u2013"
    some_span = "18:00"
    some_span_it_ran_to = "21:47"
    claim_with_its_dash_escaped = (
        f"The change record for {some_span}{some_escape_the_model_wrote}"
        f"{some_span_it_ran_to} is complete."
    )

    Scenario() \
        .given(claim_with_its_dash_escaped) \
        .when(lambda: with_escapes_resolved(claim_with_its_dash_escaped)) \
        .then(_it_reads(
            f"The change record for {some_span}{the_character_it_names}"
            f"{some_span_it_ran_to} is complete."
        ))


@pytest.mark.unit
def test_a_character_escaped_more_than_once_is_still_that_character() -> None:
    # Also what the model actually sent, and the reason a single decode is not
    # enough: it escaped the backslash of its own escape, so the arrow arrives
    # behind two of them. A repair that peeled one layer would leave `\\u2192`
    # standing in the sentence and look like it had worked.
    the_character_it_names = "→"
    some_escape_the_model_wrote_twice = "\\\\u2192"
    some_flag = "monthly-spend-feature"
    some_state_it_left = "off"
    some_state_it_reached = "on"
    claim_with_its_arrow_escaped_twice = (
        f"Two flags flipped ({some_flag} {some_state_it_left}"
        f"{some_escape_the_model_wrote_twice}{some_state_it_reached})."
    )

    Scenario() \
        .given(claim_with_its_arrow_escaped_twice) \
        .when(lambda: with_escapes_resolved(claim_with_its_arrow_escaped_twice)) \
        .then(_it_reads(
            f"Two flags flipped ({some_flag} {some_state_it_left}"
            f"{the_character_it_names}{some_state_it_reached})."
        ))


@pytest.mark.unit
def test_a_character_the_model_wrote_directly_is_left_as_it_wrote_it() -> None:
    # The ordinary case, and by far the common one - the model writes the arrow
    # itself far more often than it escapes it. The expectation is the claim,
    # because a repair that touched an answer needing none would be rewriting
    # what the model said.
    some_arrow_the_model_wrote = "→"
    claim_carrying_a_written_arrow = (
        f"Latency climbed (220ms {some_arrow_the_model_wrote} 1800ms at 21:36)."
    )

    Scenario() \
        .given(claim_carrying_a_written_arrow) \
        .when(lambda: with_escapes_resolved(claim_carrying_a_written_arrow)) \
        .then(_it_reads(claim_carrying_a_written_arrow))


@pytest.mark.unit
def test_an_escape_naming_no_character_is_left_exactly_as_written() -> None:
    # Guessing at a malformed escape would be inventing what the model meant.
    # Shown as it arrived, a reader can see that something came through wrong;
    # repaired by guesswork, they would read a claim nobody made.
    #
    # Which malformed sequence it is does not matter, only that it opens like
    # an escape - that is what carries it into the repair at all, and naming no
    # character is what has to carry it back out untouched.
    some_escape_naming_no_character = "\\uZZZZ"
    claim_with_a_malformed_escape = (
        f"The ramp wrote {some_escape_naming_no_character} into the summary."
    )

    Scenario() \
        .given(claim_with_a_malformed_escape) \
        .when(lambda: with_escapes_resolved(claim_with_a_malformed_escape)) \
        .then(_it_reads(claim_with_a_malformed_escape))


@pytest.mark.unit
def test_a_backslash_that_names_no_character_at_all_is_left_alone() -> None:
    # The reason this repair is narrower than a general unescape. It runs over
    # every tool argument of every agent, and Code-Fix's arguments are source
    # code: a `\n` inside a proposed string literal is two characters the model
    # meant, and a repair that turned it into a line break would edit the fix.
    some_line_break_in_proposed_code = "\\n"
    some_proposed_code = f'print("first{some_line_break_in_proposed_code}second")'

    Scenario() \
        .given(some_proposed_code) \
        .when(lambda: with_escapes_resolved(some_proposed_code)) \
        .then(_it_reads(some_proposed_code))


@pytest.mark.unit
def test_half_a_character_is_left_as_written_rather_than_half_resolved() -> None:
    # A character outside the basic plane is escaped as two halves, and half of
    # one is not a character. Resolved anyway it becomes a lone surrogate: a
    # string Python holds happily and cannot encode, so the failure would
    # surface as a page that will not render rather than as a sentence that
    # reads oddly. Left as written, the worst case stays the worst case here -
    # a reader sees the escape.
    some_half_a_character = "\\ud83d"
    claim_carrying_half_a_character = f"The summary opened with {some_half_a_character}."

    Scenario() \
        .given(claim_carrying_half_a_character) \
        .when(lambda: with_escapes_resolved(claim_carrying_half_a_character)) \
        .then(_it_reads(claim_carrying_half_a_character))


def _it_reads(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"expected [{expected}], got [{said}]")

        return True

    return assertion
