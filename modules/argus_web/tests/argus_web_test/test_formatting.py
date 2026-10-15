"""How the page marks up prose it shows.

The words a value comes out as are `postmortem_rendering`'s, and tested there -
which of them are labels with a row to lead to, and which names open somewhere,
included; what is left here is what only a page does - writing each as an
anchor in markup. Each case is one piece of prose and the markup it must come
out as.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from argus_web.formatting import with_references


@pytest.mark.unit
def test_a_label_in_prose_links_to_the_row_it_names() -> None:
    Scenario() \
        .given(
            some_prose := "C1 was refuted once M2 failed to clear it."
        ) \
        .when(
            lambda: with_references(some_prose, labels={"C1", "M2"}, addresses={})
        ) \
        .then(
            the_answer_was(
                '<a href="#C1">C1</a> was refuted once '
                '<a href="#M2">M2</a> failed to clear it.'
            )
        )


@pytest.mark.unit
def test_a_name_in_prose_with_an_address_opens_there_away_from_the_page() -> None:
    # A revision the prose names opens on the host it lives on, as every link
    # off the page does - in a tab of its own, telling the host nothing.
    commit = "https://github.com/acme/shop/commit/7c3ca00"

    Scenario() \
        .given(
            some_prose := "The deploy of revision 7c3ca00 broke it."
        ) \
        .when(
            lambda: with_references(some_prose, labels=set(), addresses={"7c3ca00": commit})
        ) \
        .then(
            the_answer_was(
                f'The deploy of revision <a href="{commit}" target="_blank" '
                f'rel="noopener noreferrer">7c3ca00</a> broke it.'
            )
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
            lambda: with_references(some_prose, labels={"C1"}, addresses={})
        ) \
        .then(
            the_answer_was(
                '<a href="#C1">C1</a> held '
                '&lt;script&gt;alert(1)&lt;/script&gt; &amp; lost.'
            )
        )
