from __future__ import annotations

import pytest
from argus_narration.logs import LogLine, a_log_line, the_minutes_logged
from argus_testkit import Assertion, Scenario, all_of

"""One log line as the service wrote it, read off into the columns a table shows.

The line itself travels alongside whatever is made of it, because the line is
the evidence: `when` and `message` are an arrangement for reading and never a
substitute for what came back. So every case here checks that the original
survived as well as that the arrangement is right.

The log store belongs to the service rather than to Argus. A line it never
labelled is still a line Argus read, and a line that merely mentions an error
is not a line at error level - which is why the level is looked for only where
the service writes one, and taken as prose everywhere else.
"""

SOME_MINUTE = "2026-08-30T10:12"
ANOTHER_MINUTE = "2026-08-30T10:13"
SOME_MESSAGE = "io-shop: account page rendered"


@pytest.mark.unit
def test_every_level_the_service_writes_is_read_as_the_pages_own_name_for_it() -> None:
    # At a glance, in a page a reader is scanning while an incident runs. A wall
    # of undifferentiated lines is a wall. Asserted whole rather than one level
    # per test, because what matters is that the vocabularies line up.
    Scenario() \
        .given(
            a_line_at_each_level := [
                _a_line_saying("INFO"),
                _a_line_saying("WARN"),
                _a_line_saying("WARNING"),
                _a_line_saying("ERROR")
            ]
        ) \
        .when(lambda: [a_log_line(text).level for text in a_line_at_each_level]) \
        .then(_the_levels_are(["info", "warn", "warn", "error"]))


@pytest.mark.unit
def test_a_level_word_further_into_a_line_is_prose() -> None:
    # The service writes the minute first and the level second. A line that
    # mentions an error is not a line at error level, and a page that reddened
    # it would be reporting a severity nobody claimed.
    some_line_merely_mentioning_a_level = (
        f"{SOME_MINUTE}:00Z io-shop: an ERROR was mentioned here"
    )

    Scenario() \
        .given(some_line_merely_mentioning_a_level) \
        .when(lambda: a_log_line(some_line_merely_mentioning_a_level)) \
        .then(_it_is_at_no_level())


@pytest.mark.unit
def test_a_line_that_announces_no_level_is_still_shown_at_no_level() -> None:
    # The log store is the service's, not Argus's, and a line it never labelled
    # is still a line Argus read. Shown with its whole text as the message,
    # because there is no level token to take out of it.
    some_line_announcing_no_level = f"{SOME_MINUTE}:00Z {SOME_MESSAGE}"

    Scenario() \
        .given(some_line_announcing_no_level) \
        .when(lambda: a_log_line(some_line_announcing_no_level)) \
        .then(all_of(_it_is_at_no_level(), _its_message_reads(SOME_MESSAGE)))


@pytest.mark.unit
def test_the_level_token_is_taken_out_of_the_message_it_labelled() -> None:
    # It is shown as the row's own column. Left in the message as well, every
    # line would say its severity twice - once as a mark and once as a word.
    some_line_at_a_level = _a_line_saying("ERROR")

    Scenario() \
        .given(some_line_at_a_level) \
        .when(lambda: a_log_line(some_line_at_a_level)) \
        .then(_its_message_reads(SOME_MESSAGE))


@pytest.mark.unit
def test_a_line_is_carried_exactly_as_the_service_wrote_it() -> None:
    # The arrangement is for reading; the line is the evidence. What the page
    # shows can always be checked against what came back, which is only true
    # while the original is still there to check against.
    some_line_at_a_level = _a_line_saying("ERROR")

    Scenario() \
        .given(some_line_at_a_level) \
        .when(lambda: a_log_line(some_line_at_a_level)) \
        .then(_its_text_is(some_line_at_a_level))


@pytest.mark.unit
def test_a_stamped_line_says_its_moment_to_the_second() -> None:
    # Two lines in one minute are still two lines, so a log line's own stamp is
    # kept at the granularity the service wrote it at.
    some_instant = f"{SOME_MINUTE}:37Z"
    the_second_it_reads_as = some_instant[11:19]
    some_stamped_line = f"{some_instant} {SOME_MESSAGE}"

    Scenario() \
        .given(some_stamped_line) \
        .when(lambda: a_log_line(some_stamped_line)) \
        .then(all_of(_its_stamp_is(some_instant), _it_happened_at(the_second_it_reads_as)))


@pytest.mark.unit
def test_a_line_the_service_stamped_with_nothing_carries_no_moment() -> None:
    # Distinct from a line whose stamp could not be read: there is nothing to
    # show rather than something shown wrong, and the whole line is the message.
    some_line_with_no_stamp = SOME_MESSAGE

    Scenario() \
        .given(some_line_with_no_stamp) \
        .when(lambda: a_log_line(some_line_with_no_stamp)) \
        .then(all_of(_its_stamp_is(None),
                     _it_happened_at(""),
                     _its_message_reads(SOME_MESSAGE)))


@pytest.mark.unit
def test_the_minutes_the_page_holds_lines_for_are_listed_once_each() -> None:
    # What a finding's link is matched against. A minute the page holds several
    # lines for is one row to link to, and the anchor is the minute rather than
    # the second because that is the granularity a finding cites.
    Scenario() \
        .given(
            two_minutes_of_lines := [
                a_log_line(f"{SOME_MINUTE}:01Z {SOME_MESSAGE}"),
                a_log_line(f"{SOME_MINUTE}:37Z {SOME_MESSAGE} again"),
                a_log_line(f"{ANOTHER_MINUTE}:00Z {SOME_MESSAGE} later")
            ]
        ) \
        .when(lambda: the_minutes_logged(two_minutes_of_lines)) \
        .then(_the_minutes_are([SOME_MINUTE, ANOTHER_MINUTE]))


@pytest.mark.unit
def test_a_line_with_no_stamp_puts_no_minute_on_the_page() -> None:
    # It is still shown in the table; it just cannot be linked to, because
    # there is no minute to anchor on and inventing one would point a reader at
    # a row this line does not belong to.
    Scenario() \
        .given(
            one_stamped_line_and_one_without := [
                a_log_line(f"{SOME_MINUTE}:01Z {SOME_MESSAGE}"),
                a_log_line(SOME_MESSAGE)
            ]
        ) \
        .when(lambda: the_minutes_logged(one_stamped_line_and_one_without)) \
        .then(_the_minutes_are([SOME_MINUTE]))


def _a_line_saying(level: str) -> str:
    """One stamped line at whatever level the service announced.

    The level goes where the service writes it - straight after the stamp -
    because where it sits is half of what the reading turns on.
    """
    return f"{SOME_MINUTE}:00Z {level} {SOME_MESSAGE}"


def _the_levels_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(read: list[str]) -> bool:
        if read != expected:
            raise AssertionError(f"expected the levels {expected}, got {read}")

        return True

    return assertion


def _it_is_at_no_level() -> Assertion[LogLine]:
    def assertion(line: LogLine) -> bool:
        if line.level != "plain":
            raise AssertionError(
                f"expected a line at no level, got one at [{line.level}]"
            )

        return True

    return assertion


def _its_message_reads(expected: str) -> Assertion[LogLine]:
    def assertion(line: LogLine) -> bool:
        if line.message != expected:
            raise AssertionError(f"expected [{expected}], got [{line.message}]")

        return True

    return assertion


def _its_text_is(expected: str) -> Assertion[LogLine]:
    def assertion(line: LogLine) -> bool:
        if line.text != expected:
            raise AssertionError(
                f"expected the line to be carried as [{expected}], got [{line.text}]"
            )

        return True

    return assertion


def _its_stamp_is(expected: str | None) -> Assertion[LogLine]:
    def assertion(line: LogLine) -> bool:
        if line.stamp != expected:
            raise AssertionError(f"expected the stamp [{expected}], got [{line.stamp}]")

        return True

    return assertion


def _it_happened_at(expected: str) -> Assertion[LogLine]:
    def assertion(line: LogLine) -> bool:
        if line.when != expected:
            raise AssertionError(f"expected [{expected}], got [{line.when}]")

        return True

    return assertion


def _the_minutes_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(minutes: list[str]) -> bool:
        if minutes != expected:
            raise AssertionError(f"expected the minutes {expected}, got {minutes}")

        return True

    return assertion
