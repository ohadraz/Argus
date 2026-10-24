"""A model's instant, said the way the rest of the page says instants.

One repair, and one fact about how a language model happens to write: it names
a time in the wire format the tools speak, where every other time on the page
is a clock time. The repair is presentation and changes nothing that was
claimed - which is the line this draws, because the mistake in the other
direction is a page that quietly rewrites what the investigation said.

Each case is one sentence filled in twice: once as the model wrote it, once as
the page says it. The claim and the expectation are then visibly the same
sentence, and the only difference between them is the repair being tested - so
a repair that reached one word further shows up as a difference rather than
hiding inside a second string somebody typed out by hand.

Two repairs have left. A flag's position was four regexes deciding which of the
`on`s and `off`s in a sentence were states and which were English; the model
states them as fields now. A line break was typesetting nobody asked for, and
is mended where the answer is accepted, so the postmortem and the pager read
the same sentence this page does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from argus_narration.prose import InstantInProse, said_plainly, the_instants_in
from argus_testkit import Scenario, the_answer_was


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
        .then(the_answer_was(f"The error rate rose at {the_minute_it_reads_as}."))


@pytest.mark.unit
def test_a_wire_format_instant_on_a_second_keeps_its_second() -> None:
    # As every instant is said. Cut to its minute, a time the model quoted to
    # the second reads a minute away from the same instant in the table.
    some_instant = "2026-08-30T10:14:37Z"
    the_second_it_reads_as = some_instant[11:19]
    some_claim_naming_a_wire_format_instant = f"The alert fired at {some_instant}."

    Scenario() \
        .given(some_claim_naming_a_wire_format_instant) \
        .when(lambda: said_plainly(some_claim_naming_a_wire_format_instant)) \
        .then(the_answer_was(f"The alert fired at {the_second_it_reads_as}."))


@pytest.mark.unit
@pytest.mark.parametrize(("zoned", "said"), [
    ("10:14:37Z", "10:14:37"),
    ("10:14:00Z", "10:14")
], ids=["on-a-second", "on-the-minute"])
def test_a_zoned_clock_time_is_said_to_the_second_only_where_it_has_one(zoned: str,
                                                                        said: str) -> None:
    some_claim_naming_a_zoned_clock_time = f"The alert fired at {zoned}."

    Scenario() \
        .given(some_claim_naming_a_zoned_clock_time) \
        .when(lambda: said_plainly(some_claim_naming_a_zoned_clock_time)) \
        .then(the_answer_was(f"The alert fired at {said}."))


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
        .then(the_answer_was(f"The last good minute was {some_clock_time}."))


@pytest.mark.unit
def test_an_instant_on_another_day_than_the_one_beside_it_keeps_its_date() -> None:
    # A clock time is read as the day of the line it sits on, so an instant a
    # week before that line has to say which day it was.
    some_claim_naming_an_instant_a_week_earlier = "The deploy at 2026-08-23T10:14:00Z broke it."

    Scenario() \
        .given(some_claim_naming_an_instant_a_week_earlier) \
        .when(lambda: said_plainly(some_claim_naming_an_instant_a_week_earlier,
                                   beside="2026-08-30T10:15:00Z")) \
        .then(the_answer_was("The deploy at Aug 23 10:14 broke it."))


@pytest.mark.unit
def test_a_clock_time_the_model_already_wrote_is_left_exactly_as_it_is() -> None:
    # The common case, and the one that needs no repair: the model writes for a
    # person more often than it quotes the wire. The expectation is the claim,
    # because a rendering that touched a time already in the page's own format
    # would be rewriting what the investigation said.
    some_claim_naming_a_clock_time = "The error rate rose at 10:14 and held there."

    Scenario() \
        .given(some_claim_naming_a_clock_time) \
        .when(lambda: said_plainly(some_claim_naming_a_clock_time)) \
        .then(the_answer_was(some_claim_naming_a_clock_time))


@pytest.mark.unit
def test_every_instant_in_a_sentence_is_found_with_the_moment_it_names() -> None:
    # One finder for every reader of a model's words: the page says each on
    # its clock, and the postmortem as a moment of its own. Left two, one
    # reader found a zoned clock time and the other did not. A zoned clock time
    # is put on the day the sentence is read on.
    a_wire_instant = "2026-10-18T16:36:00Z"
    a_zoned_clock_time = "19:29:35Z"
    some_claim = f"Stale from {a_wire_instant}, and served stale at {a_zoned_clock_time}."
    first, second = some_claim.index(a_wire_instant), some_claim.index(a_zoned_clock_time)

    Scenario() \
        .given(some_claim) \
        .when(lambda: the_instants_in(some_claim, date(2026, 10, 18))) \
        .then(the_answer_was([
            InstantInProse(start=first, end=first + len(a_wire_instant),
                           at=datetime(2026, 10, 18, 16, 36, tzinfo=UTC)),
            InstantInProse(start=second, end=second + len(a_zoned_clock_time),
                           at=datetime(2026, 10, 18, 19, 29, 35, tzinfo=UTC))]))
