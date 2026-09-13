from __future__ import annotations

import pytest
from argus_core.models.evidence import Evidence
from argus_core.timestamps import parse_iso
from argus_narration.findings import Finding, a_finding, pointed_at
from argus_testkit import Assertion, Scenario, all_of

"""One cited fact, pointed at the row it names.

A link is worse than no link when it is wrong: a reader who follows one
believes what it lands on. So the rule is narrow on purpose - a finding links
to a minute only where the Investigator said which moment it cited, and that
moment is one the page actually holds.

The moment is a field the model filled in, not something read back out of the
sentence. That is the whole of what changed here: the words of a claim decide
nothing at all now, which is why every sentence below is arbitrary and every
moment is not.
"""


@pytest.mark.unit
def test_a_finding_citing_a_minute_on_the_page_points_at_it() -> None:
    # The ordinary case: the investigation cited a moment, the page holds that
    # minute, and a reader can go and look at it.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    another_minute_the_page_holds = "2026-08-30T10:15:00Z"
    dont_care_claim = "Errors climbed sharply."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim,
                              at=parse_iso(some_minute_the_page_holds))
        ) \
        .when(lambda: a_finding(
            cited,
            minutes=[some_minute_the_page_holds, another_minute_the_page_holds]
        )) \
        .then(_it_links_to_the_minute(some_minute_the_page_holds))


@pytest.mark.unit
def test_a_finding_cited_partway_through_a_minute_points_at_that_minute() -> None:
    # A claim rests on the bucket its moment falls in, and a bucket is a minute
    # wide. Compared to the second, a claim cited at 10:14:42 would match none
    # of the rows the page holds and the link would vanish for no reason a
    # reader could see.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    some_moment_inside_it = "2026-08-30T10:14:42Z"
    dont_care_claim = "The account page failed."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim, at=parse_iso(some_moment_inside_it))
        ) \
        .when(lambda: a_finding(cited, minutes=[some_minute_the_page_holds])) \
        .then(_it_links_to_the_minute(some_minute_the_page_holds))


@pytest.mark.unit
def test_a_finding_about_a_minute_nobody_retrieved_gets_no_link() -> None:
    # A link has to land on a row that exists. A moment nothing read names no
    # row here, and a link into an empty table is a reader sent looking for
    # evidence the page does not hold.
    some_minute_nobody_read = "2026-08-30T09:03:00Z"
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    dont_care_claim = "Something happened."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim,
                              at=parse_iso(some_minute_nobody_read))
        ) \
        .when(lambda: a_finding(cited, minutes=[some_minute_the_page_holds])) \
        .then(_it_links_to_no_minute())


@pytest.mark.unit
def test_a_finding_that_names_no_moment_gets_no_link() -> None:
    # What the model actually sends for an absence: "no changes were recorded
    # for this service in that window" rests on there being no row, which
    # happened at no instant. Nothing to point at is the ordinary case here,
    # not a failure - and a plausible minute invented for it would link to a
    # row the claim does not rest on.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    dont_care_claim = "The ramp completed and the fallback was left in place."

    Scenario() \
        .given(cited := Evidence(claim=dont_care_claim, at=None)) \
        .when(lambda: a_finding(cited,
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
    dont_care_claim = "The account page failed."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim,
                              at=parse_iso(some_minute_the_page_holds))
        ) \
        .when(lambda: a_finding(cited,
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
    dont_care_claim = "The account page failed."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim,
                              at=parse_iso(some_minute_the_page_holds))
        ) \
        .when(lambda: a_finding(cited,
                                minutes=[some_minute_the_page_holds],
                                logged=no_minute_has_lines)) \
        .then(all_of(_it_links_to_the_minute(some_minute_the_page_holds),
                     _it_links_to_no_lines()))


@pytest.mark.unit
def test_a_finding_offered_no_rows_at_all_links_nowhere() -> None:
    # How a candidate line is first built: the findings are shaped before it is
    # known which minutes the page will hold, and pointed at them afterwards.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    dont_care_claim = "Errors climbed sharply."

    Scenario() \
        .given(
            cited := Evidence(claim=dont_care_claim,
                              at=parse_iso(some_minute_the_page_holds))
        ) \
        .when(lambda: a_finding(cited)) \
        .then(all_of(_it_links_to_no_minute(), _it_links_to_no_lines()))


@pytest.mark.unit
def test_a_finding_shaped_before_the_page_knew_its_rows_is_pointed_at_them_after()\
        -> None:
    # The other half of the case above, and why the moment travels on the
    # finding: the link is worked out a second time, once every retrieval has
    # been read, and by then the claim has already been arranged for a reader.
    # A second pass that went back to the sentence would be parsing prose the
    # page itself rewrote.
    some_minute_the_page_holds = "2026-08-30T10:14:00Z"
    the_minute_its_lines_are_keyed_by = some_minute_the_page_holds[:16]
    dont_care_claim = "Errors climbed sharply."
    shaped_before_the_rows_were_known = a_finding(
        Evidence(claim=dont_care_claim, at=parse_iso(some_minute_the_page_holds))
    )

    Scenario() \
        .given(shaped_before_the_rows_were_known) \
        .when(lambda: pointed_at(shaped_before_the_rows_were_known,
                                 minutes=[some_minute_the_page_holds],
                                 logged=[the_minute_its_lines_are_keyed_by])) \
        .then(all_of(_it_links_to_the_minute(some_minute_the_page_holds),
                     _it_links_to_the_lines(the_minute_its_lines_are_keyed_by)))


@pytest.mark.unit
def test_the_text_of_a_finding_is_said_the_way_the_page_says_things() -> None:
    # The same repair every other model-written sentence on the page gets. A
    # finding quoted in the wire format beside a table of clock times reads as
    # a different kind of fact.
    some_instant = "2026-08-30T10:14:00Z"
    the_clock_time_it_reads_as = some_instant[11:16]
    claim_naming_an_instant = f"Errors climbed sharply at {some_instant}."

    Scenario() \
        .given(
            cited := Evidence(claim=claim_naming_an_instant, at=parse_iso(some_instant))
        ) \
        .when(lambda: a_finding(cited, minutes=[some_instant])) \
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
