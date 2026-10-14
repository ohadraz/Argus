"""How a stored value is written for a reader.

Formatting belongs to whatever shows the value, never to what stores it: the
document keeps every amount at the precision it was computed to, and only the
page rounds. Each case is one value and the words it must come out as.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from argus_testkit import Scenario, the_answer_was
from argus_web.formatting import as_money, as_revision, as_span, with_references


@pytest.mark.unit
def test_money_is_shown_to_two_places_with_its_thousands_grouped() -> None:
    Scenario() \
        .given(
            some_loss := Decimal("1736.68485900091116011163646")
        ) \
        .when(
            lambda: as_money(some_loss)
        ) \
        .then(
            the_answer_was("1,736.68")
        )


@pytest.mark.unit
def test_half_a_cent_rounds_up() -> None:
    # As a till rounds, not as a statistician does: a reader checking the
    # figure by hand rounds half up, and a page rounding half to even would
    # disagree with them whenever the cent below is even.
    Scenario() \
        .given(
            some_amount := Decimal("0.125")
        ) \
        .when(
            lambda: as_money(some_amount)
        ) \
        .then(
            the_answer_was("0.13")
        )


@pytest.mark.unit
def test_a_whole_amount_still_shows_its_cents() -> None:
    Scenario() \
        .given(
            some_amount := Decimal("500")
        ) \
        .when(
            lambda: as_money(some_amount)
        ) \
        .then(
            the_answer_was("500.00")
        )


@pytest.mark.unit
def test_a_span_under_an_hour_is_minutes_and_seconds() -> None:
    Scenario() \
        .given(
            some_gap := timedelta(minutes=2, seconds=40)
        ) \
        .when(
            lambda: as_span(some_gap)
        ) \
        .then(
            the_answer_was("2m 40s")
        )


@pytest.mark.unit
def test_a_span_of_hours_names_every_unit_below_the_first() -> None:
    # A zero in the middle is said, so the units line up with what a reader
    # expects to find in each place.
    Scenario() \
        .given(
            some_duration := timedelta(hours=1, seconds=5)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("1h 0m 5s")
        )


@pytest.mark.unit
def test_a_span_of_days_names_every_unit_down_to_the_second() -> None:
    # Hours roll over into days as seconds roll into minutes; nothing below
    # the largest unit is dropped, however long the span.
    Scenario() \
        .given(
            some_duration := timedelta(days=7, minutes=3, seconds=5)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("7d 0h 3m 5s")
        )


@pytest.mark.unit
def test_a_span_under_a_minute_is_seconds() -> None:
    Scenario() \
        .given(
            some_gap := timedelta(seconds=45)
        ) \
        .when(
            lambda: as_span(some_gap)
        ) \
        .then(
            the_answer_was("45s")
        )


@pytest.mark.unit
def test_a_span_is_rounded_to_the_second() -> None:
    # A duration measured in hours arrives with a fraction of a second no
    # reader needs, and printed it would read as a precision nobody measured.
    Scenario() \
        .given(
            some_duration := timedelta(seconds=9.6)
        ) \
        .when(
            lambda: as_span(some_duration)
        ) \
        .then(
            the_answer_was("10s")
        )


@pytest.mark.unit
def test_a_label_in_prose_links_to_the_row_it_names() -> None:
    Scenario() \
        .given(
            some_prose := "C1 was refuted once M2 failed to clear it."
        ) \
        .when(
            lambda: with_references(some_prose, labels={"C1", "M2"})
        ) \
        .then(
            the_answer_was(
                '<a href="#C1">C1</a> was refuted once '
                '<a href="#M2">M2</a> failed to clear it.'
            )
        )


@pytest.mark.unit
def test_a_label_is_linked_only_where_it_stands_as_a_whole_word() -> None:
    # AI-1 is the start of AI-12, and C1 of C10: a page with only the shorter
    # row must not link the longer label's first characters to it.
    Scenario() \
        .given(
            some_prose := "AI-12 and C10 are not AI-1 or C1."
        ) \
        .when(
            lambda: with_references(some_prose, labels={"AI-1", "C1"})
        ) \
        .then(
            the_answer_was(
                'AI-12 and C10 are not '
                '<a href="#AI-1">AI-1</a> or <a href="#C1">C1</a>.'
            )
        )


@pytest.mark.unit
def test_prose_on_a_page_with_no_rows_to_link_to_is_left_as_written() -> None:
    # A postmortem with no hypotheses, no actions and no action items still
    # has prose, and it may still name labels - none of them has a row here.
    Scenario() \
        .given(
            some_prose := "Nothing was tried before C1 was ruled out."
        ) \
        .when(
            lambda: with_references(some_prose, labels=set())
        ) \
        .then(
            the_answer_was("Nothing was tried before C1 was ruled out.")
        )


@pytest.mark.unit
def test_prose_is_escaped_so_only_the_links_are_markup() -> None:
    # The prose is the model's, and the page marks the result safe: anything
    # in it that reads as markup must arrive as text.
    Scenario() \
        .given(
            some_prose := "C1 held <script>alert(1)</script> & lost."
        ) \
        .when(
            lambda: with_references(some_prose, labels={"C1"})
        ) \
        .then(
            the_answer_was(
                '<a href="#C1">C1</a> held '
                '&lt;script&gt;alert(1)&lt;/script&gt; &amp; lost.'
            )
        )


@pytest.mark.unit
def test_a_commit_is_shown_by_its_first_seven_characters() -> None:
    # As git shows one: forty characters is a line of noise, and seven is what
    # a reader pastes into git to find it.
    Scenario() \
        .given(
            some_commit := "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
        ) \
        .when(
            lambda: as_revision(some_commit)
        ) \
        .then(
            the_answer_was("26f1d7e")
        )


@pytest.mark.unit
@pytest.mark.parametrize("revision", ["v2.4.1", "26f1d7e", "release-2026-10-05"])
def test_a_revision_that_is_not_a_whole_commit_is_shown_as_written(revision: str) -> None:
    # A deployment's state is whatever the investigation called it. Cut to
    # seven, a tag or an already-short commit would lose what names it.
    Scenario() \
        .given(
            revision
        ) \
        .when(
            lambda: as_revision(revision)
        ) \
        .then(
            the_answer_was(revision)
        )
