from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of
from argus_web.views.findings import Finding, a_finding

"""One cited fact, pointed at the row it names.

A link is worse than no link when it is wrong: a reader who follows one
believes what it lands on. So the rule is narrow on purpose - a finding links
to a minute only where it quotes a time that parses into a minute the page
actually holds, and prose is never matched to a log line at all, because the
model writes *about* the lines rather than quoting them.

Nothing here turns on the words of a claim. What decides a link is the minute
inside it and whether the page holds that minute, so the sentences are
arbitrary and the minutes are not - which is what the names say.

The comparison is the subject of most of these. Times are matched minute
against minute and never as text inside text, which is what stops `21:00`
linking to the minute half an hour away that merely contains it in its seconds.
"""


@pytest.mark.unit
def test_a_finding_quoting_a_minute_on_the_page_points_at_it() -> None:
    # The ordinary case: the investigation cited a time, the page holds that
    # minute, and a reader can go and look at it.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    another_minute_the_page_holds = "2026-08-30T10:15:00Z"
    some_claim_naming_a_minute = f"Errors climbed sharply at {some_minute_the_page_holds}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(
            some_claim_naming_a_minute,
            minutes=[some_minute_the_page_holds, another_minute_the_page_holds]
        )) \
        .then(_it_links_to_the_minute(some_minute_the_page_holds))


@pytest.mark.unit
def test_a_finding_quoting_a_clock_time_points_at_the_minute_it_names() -> None:
    # The model writes for a person as often as it writes in the wire format,
    # and a reader gets the same link either way. The two spellings are the same
    # instant, which is why the clock time is sliced out of it rather than
    # written down a second time.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_minute_the_page_holds[11:16]
    some_claim_naming_a_minute = f"Errors climbed sharply at {the_clock_time_it_reads_as}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[some_minute_the_page_holds])) \
        .then(_it_links_to_the_minute(some_minute_the_page_holds))


@pytest.mark.unit
def test_a_minute_is_matched_as_a_minute_and_never_as_text_inside_text() -> None:
    # The trap this rule exists for, and the one case here where the values are
    # the whole test. `21:00` occurs inside `2026-08-30T20:21:00Z` - at its
    # seconds - so a link built by searching for one string inside the other
    # points confidently at a minute half an hour away from the one cited.
    the_minute_the_claim_names = "21:00"
    a_minute_whose_seconds_contain_it = "2026-08-30T20:21:00Z"
    some_claim_naming_a_minute = f"The last good reading was {the_minute_the_claim_names}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[a_minute_whose_seconds_contain_it])) \
        .then(_it_links_to_no_minute())


@pytest.mark.unit
def test_a_finding_about_a_minute_nobody_retrieved_gets_no_link() -> None:
    # A link has to land on a row that exists. A time nothing read names no row
    # here, however well it parses - and a link into an empty table is a reader
    # sent looking for evidence the page does not hold.
    some_minute_nobody_read = "2026-08-30T09:03:00Z"
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    some_claim_naming_a_minute = f"Something happened at {some_minute_nobody_read}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[some_minute_the_page_holds])) \
        .then(_it_links_to_no_minute())


@pytest.mark.unit
def test_a_finding_naming_no_time_at_all_gets_no_link() -> None:
    # Most findings are like this: a claim about what changed, with no instant
    # in it. Nothing to point at is the ordinary case, not a failure.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    some_claim_naming_no_minute = "The ramp completed and the fallback was left in place."

    Scenario() \
        .given(some_claim_naming_no_minute) \
        .when(lambda: a_finding(some_claim_naming_no_minute,
                                minutes=[some_minute_the_page_holds],
                                logged=[some_minute_the_page_holds[:16]])) \
        .then(all_of(_it_links_to_no_minute(), _it_links_to_no_lines()))


@pytest.mark.unit
def test_the_lines_of_a_minute_are_linked_separately_from_its_numbers() -> None:
    # Two links because they answer different questions - what the numbers did,
    # and what the service said - and a reader checking a claim usually wants
    # the second. The log rows are keyed by the minute rather than the second,
    # which is why the anchor is the instant cut short.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    the_minute_its_lines_are_keyed_by = some_minute_the_page_holds[:16]
    some_claim_naming_a_minute = f"The account page failed at {some_minute_the_page_holds}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[some_minute_the_page_holds],
                                logged=[the_minute_its_lines_are_keyed_by])) \
        .then(all_of(_it_links_to_the_minute(some_minute_the_page_holds),
                     _it_links_to_the_lines(the_minute_its_lines_are_keyed_by)))


@pytest.mark.unit
def test_a_minute_with_metrics_and_no_lines_links_only_to_its_metrics() -> None:
    # The two lists are read separately because they are filled separately: a
    # window can be covered by the metrics retrieval and not by the log one.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    no_minute_has_lines: list[str] = []
    some_claim_naming_a_minute = f"The account page failed at {some_minute_the_page_holds}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[some_minute_the_page_holds],
                                logged=no_minute_has_lines)) \
        .then(all_of(_it_links_to_the_minute(some_minute_the_page_holds),
                     _it_links_to_no_lines()))


@pytest.mark.unit
def test_a_finding_offered_no_rows_at_all_links_nowhere() -> None:
    # How a candidate line is first built: the findings are shaped before it is
    # known which minutes the page will hold, and pointed at them afterwards.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    some_claim_naming_a_minute = f"Errors climbed sharply at {some_minute_the_page_holds}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute)) \
        .then(all_of(_it_links_to_no_minute(), _it_links_to_no_lines()))


@pytest.mark.unit
def test_the_text_of_a_finding_is_said_the_way_the_page_says_things() -> None:
    # The same repair every other model-written sentence on the page gets. A
    # finding quoted in the wire format beside a table of clock times reads as
    # a different kind of fact.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_minute_the_page_holds[11:16]
    some_claim_naming_a_minute = f"Errors climbed sharply at {some_minute_the_page_holds}."

    Scenario() \
        .given(some_claim_naming_a_minute) \
        .when(lambda: a_finding(some_claim_naming_a_minute,
                                minutes=[some_minute_the_page_holds])) \
        .then(_it_reads(f"Errors climbed sharply at {the_clock_time_it_reads_as}."))


def _it_links_to_the_minute(expected: str) -> Assertion[Finding]:
    def assertion(finding: Finding) -> bool:
        if finding.links_to_minute != expected:
            raise AssertionError(
                f"expected a link to the minute [{expected}], "
                f"got [{finding.links_to_minute}]"
            )

        return True

    return assertion


def _it_links_to_no_minute() -> Assertion[Finding]:
    def assertion(finding: Finding) -> bool:
        if finding.links_to_minute:
            raise AssertionError(
                "expected no link - a link that lands on the wrong row is worse "
                f"than none - got [{finding.links_to_minute}]"
            )

        return True

    return assertion


def _it_links_to_the_lines(expected: str) -> Assertion[Finding]:
    def assertion(finding: Finding) -> bool:
        if finding.links_to_lines != expected:
            raise AssertionError(
                f"expected a link to the lines of [{expected}], "
                f"got [{finding.links_to_lines}]"
            )

        return True

    return assertion


def _it_links_to_no_lines() -> Assertion[Finding]:
    def assertion(finding: Finding) -> bool:
        if finding.links_to_lines:
            raise AssertionError(
                f"expected no link to any lines, got [{finding.links_to_lines}]"
            )

        return True

    return assertion


def _it_reads(expected: str) -> Assertion[Finding]:
    def assertion(finding: Finding) -> bool:
        if finding.text != expected:
            raise AssertionError(f"expected [{expected}], got [{finding.text}]")

        return True

    return assertion
