"""A line of the postmortem: its words, in pieces, each with the part it plays.

The words are the whole of what a reader is told; the parts are what each
destination wraps around them - a subject in code on the page, in a fixed-width
face in the PDF. Each case is one line and what it says.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from argus_core.models import OpenedPullRequest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run


@pytest.mark.unit
def test_a_line_says_its_runs_in_order_whatever_part_each_plays() -> None:
    Scenario() \
        .given(
            a_line := Line(runs=(Run(text="checkout-v2", role=Role.CODE),
                                 Run(text=" flag went from "),
                                 Run(text="OFF", role=Role.FROM_STATE),
                                 Run(text=" to "),
                                 Run(text="ON", role=Role.TO_STATE),
                                 Run(text=".")))
        ) \
        .when(
            lambda: a_line.said
        ) \
        .then(
            the_answer_was("checkout-v2 flag went from OFF to ON.")
        )


@pytest.mark.unit
def test_a_moment_is_said_in_utc_and_keeps_the_instant_it_names() -> None:
    # The page says the same instant again on the reader's own clock, and a
    # file cannot - so the words are the UTC ones, and the instant rides along
    # for whoever can do more with it.
    Scenario() \
        .given(
            some_instant := datetime(2026, 10, 14, 14, 3, tzinfo=UTC)
        ) \
        .when(
            lambda: Run.a_moment(some_instant)
        ) \
        .then(
            the_answer_was(Run(text="Oct 14, 2026, 14:03 UTC", role=Role.MOMENT, at=some_instant))
        )


@pytest.mark.unit
def test_a_moment_on_the_day_given_is_said_by_its_time_alone() -> None:
    # The head says the incident's day once. A moment of that day said again
    # with its date reads as though the day might be another.
    Scenario() \
        .given(
            some_instant := datetime(2026, 10, 14, 14, 3, tzinfo=UTC)
        ) \
        .when(
            lambda: Run.a_moment(some_instant).said_on(date(2026, 10, 14))
        ) \
        .then(
            the_answer_was(Run(text="14:03 UTC", role=Role.MOMENT, at=some_instant))
        )


@pytest.mark.unit
def test_a_moment_with_seconds_is_said_to_the_second() -> None:
    # As the write-up's own figures say it. Cut to its minute, a moment beside a
    # span read a minute out: "fired at 19:12 UTC, 5m 55s later", where the
    # timeline said 19:12:55.
    Scenario() \
        .given(
            some_instant := datetime(2026, 10, 14, 14, 3, 7, tzinfo=UTC)
        ) \
        .when(
            lambda: Run.a_moment(some_instant)
        ) \
        .then(
            the_answer_was(Run(text="Oct 14, 2026, 14:03:07 UTC", role=Role.MOMENT,
                               at=some_instant))
        )


@pytest.mark.unit
def test_a_moment_with_seconds_on_the_day_given_keeps_them() -> None:
    Scenario() \
        .given(
            some_instant := datetime(2026, 10, 14, 14, 3, 7, tzinfo=UTC)
        ) \
        .when(
            lambda: Run.a_moment(some_instant).said_on(date(2026, 10, 14))
        ) \
        .then(
            the_answer_was(Run(text="14:03:07 UTC", role=Role.MOMENT, at=some_instant))
        )


@pytest.mark.unit
def test_a_moment_on_another_day_keeps_its_date() -> None:
    Scenario() \
        .given(
            some_instant := datetime(2026, 10, 14, 14, 3, tzinfo=UTC)
        ) \
        .when(
            lambda: Run.a_moment(some_instant).said_on(date(2026, 10, 13))
        ) \
        .then(
            the_answer_was(Run.a_moment(some_instant))
        )


@pytest.mark.unit
def test_a_run_that_is_no_moment_is_said_as_it_was() -> None:
    Scenario() \
        .given(
            some_run := Run(text="io-shop", role=Role.CODE)
        ) \
        .when(
            lambda: some_run.said_on(date(2026, 10, 14))
        ) \
        .then(
            the_answer_was(some_run)
        )


@pytest.mark.unit
def test_an_address_is_said_in_full_and_links_to_itself() -> None:
    # Read away from the screen it came from, an address relative to nothing
    # leads nowhere - so the words are the address, whole.
    Scenario() \
        .given(
            some_address := "https://github.com/acme/shop/pull/42"
        ) \
        .when(
            lambda: Run.an_address(some_address)
        ) \
        .then(
            the_answer_was(Run(text=some_address, role=Role.LINK, address=some_address))
        )


@pytest.mark.unit
def test_a_pull_request_is_named_by_its_number() -> None:
    # One name for it wherever the document mentions it; the address is
    # written out once, where a reader of paper looks for addresses.
    Scenario() \
        .given(
            some_pull_request := OpenedPullRequest(number=42,
                                                   url="https://github.com/acme/shop/pull/42",
                                                   branch="dont care")
        ) \
        .when(
            lambda: Run.a_pull_request(some_pull_request)
        ) \
        .then(
            the_answer_was(Run(text="PR #42"))
        )


@pytest.mark.unit
def test_a_run_linked_to_an_address_keeps_its_words_and_opens_there() -> None:
    Scenario() \
        .given(
            some_address := "https://github.com/acme/shop/pull/42"
        ) \
        .when(
            lambda: Run(text="PR #42").linked_to(some_address)
        ) \
        .then(
            the_answer_was(Run(text="PR #42", role=Role.LINK, address=some_address))
        )


@pytest.mark.unit
def test_each_label_prose_cites_is_a_citation_of_the_row_it_names() -> None:
    # AI-1 is the start of AI-12, and C1 of C10: a document with only the
    # shorter rows must not cite them by the longer labels' first characters.
    Scenario() \
        .given(
            some_prose := Run(text="C1 was refuted; AI-12 and C10 are not AI-1.", role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_citations({"C1", "AI-1"})
        ) \
        .then(
            the_answer_was((Run(text="C1", role=Role.CITATION, address="C1"),
                            Run(text=" was refuted; AI-12 and C10 are not ", role=Role.PROSE),
                            Run(text="AI-1", role=Role.CITATION, address="AI-1"),
                            Run(text=".", role=Role.PROSE)))
        )


@pytest.mark.unit
def test_a_label_is_not_cited_from_the_end_of_a_longer_word() -> None:
    # XC1 is a name of its own, which happens to end the way C1 is spelled.
    Scenario() \
        .given(
            some_prose := Run(text="XC1 and C1", role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_citations({"C1"})
        ) \
        .then(
            the_answer_was((Run(text="XC1 and ", role=Role.PROSE),
                            Run(text="C1", role=Role.CITATION, address="C1")))
        )


@pytest.mark.unit
def test_each_name_with_an_address_is_a_link_to_where_it_opens() -> None:
    # A row says where a change came from in words, and each name in them a
    # reader can open leads there: the revision, the repository, the directory.
    commit = "https://github.com/acme/shop/commit/7c3ca00"
    repository = "https://github.com/acme/shop"
    directory = "https://github.com/acme/shop/tree/7c3ca00/deploy"

    Scenario() \
        .given(
            some_words := Run(text="deployed revision 7c3ca00 from the acme/shop "
                                   "repository's deploy/ directory")
        ) \
        .when(
            lambda: some_words.with_links({"7c3ca00": commit, "acme/shop": repository,
                                           "deploy": directory})
        ) \
        .then(
            the_answer_was((Run(text="deployed revision "),
                            Run(text="7c3ca00", role=Role.LINK, address=commit),
                            Run(text=" from the "),
                            Run(text="acme/shop", role=Role.LINK, address=repository),
                            Run(text=" repository's "),
                            Run(text="deploy", role=Role.LINK, address=directory),
                            Run(text="/ directory")))
        )


@pytest.mark.unit
def test_a_name_is_not_linked_from_inside_a_longer_word() -> None:
    # "deployed" begins the way the directory deploy/ is spelled.
    directory = "https://github.com/acme/shop/tree/7c3ca00/deploy"

    Scenario() \
        .given(
            some_words := Run(text="deployed from deploy/")
        ) \
        .when(
            lambda: some_words.with_links({"deploy": directory})
        ) \
        .then(
            the_answer_was((Run(text="deployed from "),
                            Run(text="deploy", role=Role.LINK, address=directory),
                            Run(text="/")))
        )


@pytest.mark.unit
def test_prose_cites_each_label_and_links_each_name_with_an_address() -> None:
    # "The deploy of revision 7c3ca00 (P2)": the label leads to the row that
    # says what P2 was, and the revision to where a reader opens it.
    commit = "https://github.com/acme/shop/commit/7c3ca00"

    Scenario() \
        .given(
            some_prose := Run(text="The deploy of revision 7c3ca00 (P2) broke it.",
                              role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_references({"P2"}, {"7c3ca00": commit})
        ) \
        .then(
            the_answer_was((Run(text="The deploy of revision ", role=Role.PROSE),
                            Run(text="7c3ca00", role=Role.LINK, address=commit),
                            Run(text=" (", role=Role.PROSE),
                            Run(text="P2", role=Role.CITATION, address="P2"),
                            Run(text=") broke it.", role=Role.PROSE)))
        )


@pytest.mark.unit
def test_code_prose_quotes_between_backticks_is_code_without_its_backticks() -> None:
    # The write-up and the Investigator write Markdown, and a backtick printed
    # is a mark nobody reading the page or the paper was meant to see: a root
    # cause read "`http-metrics`".
    Scenario() \
        .given(
            some_prose := Run(text="The port `http-metrics` is gone (C1).", role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_references({"C1"}, {})
        ) \
        .then(
            the_answer_was((Run(text="The port ", role=Role.PROSE),
                            Run(text="http-metrics", role=Role.CODE),
                            Run(text=" is gone (", role=Role.PROSE),
                            Run(text="C1", role=Role.CITATION, address="C1"),
                            Run(text=").", role=Role.PROSE)))
        )


@pytest.mark.unit
def test_a_label_or_a_name_quoted_as_code_is_neither_cited_nor_linked() -> None:
    # Between backticks it is the code's text, quoted as it was written.
    commit = "https://github.com/acme/shop/commit/7c3ca00"

    Scenario() \
        .given(
            some_prose := Run(text="It reads `C1` and `7c3ca00`.", role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_references({"C1"}, {"7c3ca00": commit})
        ) \
        .then(
            the_answer_was((Run(text="It reads ", role=Role.PROSE),
                            Run(text="C1", role=Role.CODE),
                            Run(text=" and ", role=Role.PROSE),
                            Run(text="7c3ca00", role=Role.CODE),
                            Run(text=".", role=Role.PROSE)))
        )


@pytest.mark.unit
def test_code_quoted_in_a_run_is_cut_out_as_code_and_the_rest_keeps_the_runs_part() -> None:
    # The model's words set as the record's are Markdown too - a candidate, a
    # symptom, a lead's weighing - and their backticks were printed.
    Scenario() \
        .given(
            some_words := Run(text="the `metrics` port is gone", role=Role.QUOTE)
        ) \
        .when(
            lambda: some_words.with_code_set_apart()
        ) \
        .then(
            the_answer_was((Run(text="the ", role=Role.QUOTE),
                            Run(text="metrics", role=Role.CODE),
                            Run(text=" port is gone", role=Role.QUOTE)))
        )


@pytest.mark.unit
def test_a_run_quoting_no_code_comes_back_as_it_was() -> None:
    Scenario() \
        .given(
            some_words := Run(text="the port is gone")
        ) \
        .when(
            lambda: some_words.with_code_set_apart()
        ) \
        .then(
            the_answer_was((some_words,))
        )


@pytest.mark.unit
def test_a_label_with_no_row_to_cite_is_left_as_prose() -> None:
    # A postmortem with no hypotheses still has prose, and it may still name
    # C1 - a citation of it would lead nowhere.
    Scenario() \
        .given(
            some_prose := Run(text="Nothing was tried before C1 was ruled out.", role=Role.PROSE)
        ) \
        .when(
            lambda: some_prose.with_citations(set())
        ) \
        .then(
            the_answer_was((some_prose,))
        )
