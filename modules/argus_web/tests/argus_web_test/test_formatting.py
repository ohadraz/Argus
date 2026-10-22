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
from argus_web.formatting import from_markdown, with_references


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
def test_an_answer_in_markdown_keeps_its_bold_its_italics_and_its_code() -> None:
    Scenario() \
        .given(
            some_answer := "Reverted **the flag** *quickly* with `monthly-spend-feature`."
        ) \
        .when(
            lambda: from_markdown(some_answer)
        ) \
        .then(
            the_answer_was(
                "<p>Reverted <strong>the flag</strong> <em>quickly</em> with "
                "<code>monthly-spend-feature</code>.</p>"
            )
        )


@pytest.mark.unit
def test_a_heading_line_and_the_items_under_it_are_a_paragraph_and_a_list() -> None:
    # The shape the model answers in: a paragraph, then a bolded line with the
    # steps it covers listed straight under it.
    Scenario() \
        .given(
            some_answer := ("The record:\n\n**Investigation (14:15)**\n"
                            "- Picked up the alert.\n- Read the metrics.")
        ) \
        .when(
            lambda: from_markdown(some_answer)
        ) \
        .then(
            the_answer_was(
                "<p>The record:</p><p><strong>Investigation (14:15)</strong></p>"
                "<ul><li>Picked up the alert.</li><li>Read the metrics.</li></ul>"
            )
        )


@pytest.mark.unit
def test_anything_else_in_an_answer_in_markdown_arrives_as_text() -> None:
    # Model output on a page that marks the result safe: only the allowed few
    # become markup. A link or raw HTML let through would put the model's
    # markup on the page.
    Scenario() \
        .given(
            some_answer := ("<script>alert(1)</script> [a link](https://example.invalid) "
                            "# no heading & **unclosed")
        ) \
        .when(
            lambda: from_markdown(some_answer)
        ) \
        .then(
            the_answer_was(
                "<p>&lt;script&gt;alert(1)&lt;/script&gt; [a link](https://example.invalid) "
                "# no heading &amp; **unclosed</p>"
            )
        )


@pytest.mark.unit
def test_what_is_between_backticks_is_code_and_nothing_else() -> None:
    Scenario() \
        .given(
            some_answer := "`a**b**c`"
        ) \
        .when(
            lambda: from_markdown(some_answer)
        ) \
        .then(
            the_answer_was("<p><code>a**b**c</code></p>")
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
