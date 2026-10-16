"""A line of the account as it is shown: the square brackets Argus and its
model quote a name in, left off.

The brackets are how a name is marked off in what a model reads - "[io-shop]",
"[7c3ca00]" - and a reader of the page or the channel reads them as clutter
around a word. So they are left off where a line is shown, and only there: the
record, and what a model is told of it, keep them.

Only the brackets that quote a name. An index in code keeps its brackets, as a
phrase with spaces in it and a link do, and a line a person wrote is shown as
they wrote it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_narration import NarrationLine
from argus_narration.showing import as_shown, shown
from argus_testkit import Scenario, the_answer_was

DONT_CARE_MOMENT = datetime(2026, 10, 11, 12, 18, tzinfo=UTC)


@pytest.mark.unit
def test_a_quoted_name_is_shown_without_its_brackets() -> None:
    Scenario() \
        .when(
            lambda: as_shown("Rolled [io-shop] back to [7c3ca00], which was [3] replicas")
        ) \
        .then(
            the_answer_was("Rolled io-shop back to 7c3ca00, which was 3 replicas"))


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    "the list read prices[index] and names[0]",
    "it said [a phrase with spaces in it]",
    "see [the runbook](https://runbooks.example/io-shop)",
    "see [docs](https://runbooks.example/io-shop)",
    "a nested [[name]] stays as it was"
], ids=["an-index", "a-phrase", "a-link", "a-one-word-link", "nested"])
def test_brackets_that_quote_no_name_are_shown_as_written(said: str) -> None:
    # An index belongs to the code it is in, a phrase was bracketed by whoever
    # wrote it for a reason of their own, and a link's text is what it opens.
    Scenario() \
        .when(
            lambda: as_shown(said)
        ) \
        .then(
            the_answer_was(said))


@pytest.mark.unit
def test_a_line_of_the_walk_is_shown_without_brackets_in_any_part_of_it() -> None:
    # The marked word and the words either side of it are the same sentence
    # split for a destination that sets the word apart, and are shown alike.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="action-taken", who="Mitigation",
                              text="Rolled [io-shop] back to [7c3ca00]",
                              before_emphasis="Rolled ", emphasis="[io-shop]",
                              after_emphasis=" back to [7c3ca00]")

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line)
        ) \
        .then(
            the_answer_was(some_line.model_copy(update={
                "text": "Rolled io-shop back to 7c3ca00",
                "emphasis": "io-shop",
                "after_emphasis": " back to 7c3ca00"})))


@pytest.mark.unit
def test_a_line_a_person_wrote_is_shown_as_they_wrote_it() -> None:
    # Their brackets are theirs, and not Argus's way of quoting a name.
    some_line = NarrationLine(at=DONT_CARE_MOMENT, kind="person-wrote", who="kuki",
                              text="the [checkout] flag again?", outside_the_walk=True)

    Scenario() \
        .given(
            some_line
        ) \
        .when(
            lambda: shown(some_line)
        ) \
        .then(
            the_answer_was(some_line))
