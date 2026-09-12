"""A claim the model broke across lines, accepted as the sentence it is.

The model writes a paragraph and occasionally breaks it mid-clause, indenting
whatever continues. That is typesetting nobody asked for: a claim is one
sentence, and where it happens to wrap is the renderer's business.

Repaired where the answer is accepted rather than in whichever view shows it -
the same claim reaches a web page, a postmortem and a message to a human, and a
repair living in one of those is missing from the other two.

Narrower than the escape repair beside it, and deliberately not applied at the
same seam: that one runs over every tool argument of every agent, where this
would flatten Code-Fix's source code and the paragraph breaks of a postmortem
the model wrote on purpose. Only a claim is one line by definition.

Each case is one sentence filled in twice: once as the model wrote it, once as
it is accepted. Where nothing should change, the expectation is the sentence
itself, so a repair that reached further shows up as a difference rather than
hiding inside a second string somebody typed out by hand.
"""

from __future__ import annotations

import pytest
from argus_core.llm.line_breaks import on_one_line
from argus_testkit import Assertion, Scenario


@pytest.mark.unit
def test_a_claim_broken_across_lines_is_accepted_as_the_sentence_it_is() -> None:
    # Whatever whitespace came with the break goes with it: the model indents
    # its continuation, and the indent is no more meant than the break was.
    some_break_the_model_wrote = "\n   "
    the_space_it_stands_for = " "
    claim_broken_mid_sentence = (
        f"The error rate rose{some_break_the_model_wrote}to 33% within a minute."
    )

    Scenario() \
        .given(claim_broken_mid_sentence) \
        .when(lambda: on_one_line(claim_broken_mid_sentence)) \
        .then(_it_reads(
            f"The error rate rose{the_space_it_stands_for}to 33% within a minute."
        ))


@pytest.mark.unit
def test_a_claim_broken_in_several_places_is_still_one_sentence() -> None:
    # A model that wrapped once usually wrapped again. A repair that mended the
    # first break and left the rest would read as though it had worked.
    claim_broken_twice = (
        "monthly-spend-feature was switched on at 13:00\nand the error rate "
        "rose\n   one minute later."
    )

    Scenario() \
        .given(claim_broken_twice) \
        .when(lambda: on_one_line(claim_broken_twice)) \
        .then(_it_reads(
            "monthly-spend-feature was switched on at 13:00 and the error rate "
            "rose one minute later."
        ))


@pytest.mark.unit
def test_a_claim_padded_at_either_end_loses_the_padding() -> None:
    # The model sometimes opens or closes a field with the newline it was about
    # to write the next one on. Carried through, it becomes a leading space in
    # front of every rendering of the claim.
    some_padding = "\n  "
    claim = "The ramp completed at 13:02."

    Scenario() \
        .given(padded_claim := f"{some_padding}{claim}{some_padding}") \
        .when(lambda: on_one_line(padded_claim)) \
        .then(_it_reads(claim))


@pytest.mark.unit
def test_a_claim_the_model_wrote_on_one_line_is_left_as_it_wrote_it() -> None:
    # The ordinary case, and much the commoner one. The expectation is the
    # claim, because a repair that touched an answer needing none would be
    # rewriting what the model said.
    claim_already_on_one_line = "monthly-spend-feature evaluated on for all 198 requests."

    Scenario() \
        .given(claim_already_on_one_line) \
        .when(lambda: on_one_line(claim_already_on_one_line)) \
        .then(_it_reads(claim_already_on_one_line))


def _it_reads(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"expected [{expected}], got [{said}]")

        return True

    return assertion
