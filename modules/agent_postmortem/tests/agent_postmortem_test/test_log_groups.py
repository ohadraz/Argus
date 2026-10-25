"""The log lines an incident read, one piece of evidence per message.

A service logs one message every minute it is broken, and an evidence block
listing each copy reads as a traceback and buries the one line that differs.
Grouped, a message is said once with how often and over how long - not every
minute it was logged in, which for a fault that ran three hours is a hundred and
fifty minutes nobody reads. Named by its message, a group keeps its label in
every run - which is what lets an answer recorded in one run cite evidence in
another.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest
from agent_postmortem.log_groups import (
    LOG_GROUP_PREFIX,
    grouped,
    labels_reaching_into,
    the_groups_of,
)
from argus_core.models import CitedEvidence
from argus_testkit import Assertion, Scenario, the_answer_was

# The day this file's lines are logged on, which is the day its incident began.
ONSET_DAY = date(2026, 10, 11)
SOME_ERROR = "ERROR io-shop: account page request failed - ZeroDivisionError at spend_summary.py:47"
SOME_RATE = "WARN io-shop: account page error rate at {}% over the last minute"
SOME_SLOW_CALL = ("WARN io-shop: slow upstream call - io-pricing:8080 took {}ms for "
                  "/baskets/shopper-{} ({} of 40 requests)")


@pytest.mark.unit
def test_a_message_logged_again_is_said_once_with_how_often_and_over_how_long() -> None:
    # Every minute a fault ran, listed, is a line nobody reads to the end. The
    # numbers that held every time - the line the error is at - stay written,
    # and the span counts its first minute and its last.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:38:00Z {SOME_ERROR}",
                           f"2026-10-11T23:41:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_ERROR} - 2 occurrences in 4 minutes, 23:38–23:41"])
        )


@pytest.mark.unit
def test_two_replicas_logging_in_one_minute_are_two_occurrences() -> None:
    # Each line is one request that failed, and two replicas failing one each is
    # two failures - the minute is shared, the occurrences are not.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:38:00Z {SOME_ERROR}",
                           f"2026-10-11T23:38:00Z {SOME_ERROR}",
                           f"2026-10-11T23:41:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_ERROR} - 3 occurrences in 4 minutes, 23:38–23:41"])
        )


@pytest.mark.unit
def test_occurrences_all_in_one_minute_name_that_minute_once() -> None:
    # A span from a minute to itself reads as a typo.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:38:00Z {SOME_ERROR}",
                           f"2026-10-11T23:38:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_ERROR} - 2 occurrences in 1 minute, 23:38"])
        )


@pytest.mark.unit
def test_a_span_across_midnight_is_counted_across_it() -> None:
    # The clock reads 23:59 then 00:01, and three minutes passed, not a day less
    # two.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:59:00Z {SOME_ERROR}",
                           f"2026-10-12T00:01:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_ERROR} - 2 occurrences in 3 minutes, 23:59 – Oct 12 00:01"])
        )


@pytest.mark.unit
def test_lines_with_no_minute_are_counted_and_given_no_span() -> None:
    # A line the service did not stamp has no minute to measure from, and a
    # span made up for it would be a guess.
    Scenario() \
        .given(
            some_lines := [SOME_ERROR, SOME_ERROR]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_ERROR} - 2 occurrences"])
        )


@pytest.mark.unit
def test_what_varied_is_said_as_its_range_its_typical_value_and_its_worst_minute() -> None:
    # The rate is the one thing about the message that changed, and the reason
    # to read it at all - but as every minute's value it is the flood again.
    # Typical is a value that was logged, the middle one, never an average no
    # minute read.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                           f"2026-10-11T23:38:00Z {SOME_RATE.format('24.00')}",
                           f"2026-10-11T23:39:00Z {SOME_RATE.format('3.00')}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_RATE.format('#')} - 3 occurrences in 3 minutes, "
                            f"23:37–23:39; # was 1.50 to 24.00, typically 3.00, "
                            f"highest at 23:38"])
        )


@pytest.mark.unit
def test_a_message_logged_once_is_shown_as_it_was_logged() -> None:
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:36:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"23:36 {SOME_ERROR}"])
        )


@pytest.mark.unit
def test_messages_are_listed_in_the_order_they_were_first_logged() -> None:
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                           f"2026-10-11T23:38:00Z {SOME_ERROR}",
                           f"2026-10-11T23:39:00Z {SOME_RATE.format('24.00')}"]
        ) \
        .when(
            lambda: grouped(some_lines, None, ONSET_DAY)
        ) \
        .then(
            _groups_say_in_order(SOME_RATE.format("#"), SOME_ERROR)
        )


@pytest.mark.unit
def test_a_group_is_labelled_by_its_message_whatever_else_was_read() -> None:
    # The run an answer is replayed in reads a message more or fewer than the
    # one it was recorded in. Labelled by place, every group after the
    # difference would change its name; labelled by message, none does.
    the_error_alone = [f"2026-10-11T23:38:00Z {SOME_ERROR}"]
    with_another_message_first = [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                                  f"2026-10-11T23:41:00Z {SOME_ERROR}"]

    Scenario() \
        .given(
            the_error_alone
        ) \
        .when(
            lambda: (_label_of(SOME_ERROR, grouped(the_error_alone, None, ONSET_DAY)),
                     _label_of(SOME_ERROR, grouped(with_another_message_first, None, ONSET_DAY)))
        ) \
        .then(
            _the_same_label_twice()
        )


@pytest.mark.unit
def test_two_messages_are_labelled_apart() -> None:
    # A step citing one message has to cite that one: two groups under one
    # label would have every citation of either name both.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                           f"2026-10-11T23:38:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.label for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            _labels_differ()
        )


@pytest.mark.unit
def test_a_group_label_is_its_prefix_and_a_short_digest() -> None:
    # Short enough to cite, and shaped so the prose check reads it as a name.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:38:00Z {SOME_ERROR}"]
        ) \
        .when(
            lambda: [group.label for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            _labels_are_shaped(rf"{LOG_GROUP_PREFIX}[0-9a-f]{{4}}")
        )


@pytest.mark.unit
def test_a_number_inside_a_name_that_varied_is_said_by_how_many_names_there_were() -> None:
    # A shopper's id is a name, not a quantity: its parts' range and typical
    # value were statistics of nothing. What varied about it is how many there
    # were. A number that is a figure - the milliseconds, the count - still
    # ranges, and the key the message is grouped by is the same as ever.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {SOME_SLOW_CALL.format('2300', '1-2-3', '5')}",
                           f"2026-10-11T23:38:00Z {SOME_SLOW_CALL.format('900', '4-5-6', '7')}",
                           f"2026-10-11T23:39:00Z {SOME_SLOW_CALL.format('1200', '1-2-3', '6')}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_SLOW_CALL.format('#', '#-#-#', '#')} - 3 occurrences in "
                            f"3 minutes, 23:37–23:39; # was 900 to 2300, typically 1200, "
                            f"highest at 23:37; /baskets/shopper-#-#-# took 2 different values; "
                            f"# was 5 to 7, typically 6, highest at 23:38"])
        )


@pytest.mark.unit
def test_only_a_message_logged_in_or_after_a_stretch_s_first_minute_reaches_into_it() -> None:
    # A stretch the metrics did not cover is not one nobody saw where a message
    # read was logged inside it - and a message last logged before it says
    # nothing of it. A line is stamped with its whole minute, so one from the
    # minute the stretch began in reaches into it.
    some_lines = [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                  f"2026-10-11T23:38:00Z {SOME_ERROR}",
                  f"2026-10-11T23:41:00Z {SOME_RATE.format('24.00')}"]

    Scenario() \
        .given(
            the_stretch_began := datetime(2026, 10, 11, 23, 41, 30, tzinfo=UTC)
        ) \
        .when(
            lambda: labels_reaching_into(some_lines, the_stretch_began)
        ) \
        .then(
            the_answer_was([_label_of(SOME_RATE.format("#"), grouped(some_lines, None, ONSET_DAY))])
        )


@pytest.mark.unit
def test_a_message_with_no_minute_reaches_into_no_stretch() -> None:
    # Undated, it could have been logged anywhere, and naming it would say it
    # was logged inside.
    Scenario() \
        .given(
            some_lines := [SOME_ERROR]
        ) \
        .when(
            lambda: labels_reaching_into(some_lines, datetime(2026, 10, 11, 23, 41, tzinfo=UTC))
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_a_message_logged_on_both_sides_of_where_the_metrics_stopped_is_said_in_two_parts() -> None:
    # Summed across the stop, what the shop logged inside a stretch the metrics
    # did not cover is lost in what it logged before: told only "0.50 to 2.00"
    # over the whole half hour, a model wrote that nothing said whether shoppers
    # were affected. Before comes first, so the figures it names keep their
    # places whether or not a run is split.
    some_lines = [f"2026-10-11T23:37:00Z {SOME_RATE.format('1.50')}",
                  f"2026-10-11T23:38:00Z {SOME_RATE.format('24.00')}",
                  f"2026-10-11T23:39:00Z {SOME_RATE.format('3.00')}",
                  f"2026-10-11T23:40:00Z {SOME_RATE.format('0.50')}",
                  f"2026-10-11T23:41:00Z {SOME_RATE.format('1.00')}"]

    Scenario() \
        .given(
            the_metrics_stopped := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, the_metrics_stopped, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_RATE.format('#')} - before the metrics stopped: "
                            f"3 occurrences in 3 minutes, 23:37–23:39; # was 1.50 to 24.00, "
                            f"typically 3.00, highest at 23:38. After they stopped: "
                            f"2 occurrences in 2 minutes, 23:40–23:41; # was 0.50 to 1.00, "
                            f"typically 0.50, highest at 23:41"])
        )


@pytest.mark.unit
def test_a_part_that_read_one_value_is_said_as_that_value() -> None:
    # "0.50 to 0.50, typically 0.50" is a range of one number.
    some_lines = [f"2026-10-11T23:38:00Z {SOME_RATE.format('24.00')}",
                  f"2026-10-11T23:39:00Z {SOME_RATE.format('3.00')}",
                  f"2026-10-11T23:40:00Z {SOME_RATE.format('0.50')}"]

    Scenario() \
        .given(
            the_metrics_stopped := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, the_metrics_stopped, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_RATE.format('#')} - before the metrics stopped: "
                            f"2 occurrences in 2 minutes, 23:38–23:39; # was 3.00 to 24.00, "
                            f"typically 3.00, highest at 23:38. After they stopped: "
                            f"1 occurrence in 1 minute, 23:40; # was 0.50"])
        )


@pytest.mark.unit
def test_a_part_whose_lines_all_read_one_value_is_said_as_that_value() -> None:
    # The same range of one number as a part of one line, from two.
    some_lines = [f"2026-10-11T23:38:00Z {SOME_RATE.format('24.00')}",
                  f"2026-10-11T23:39:00Z {SOME_RATE.format('3.00')}",
                  f"2026-10-11T23:40:00Z {SOME_RATE.format('0.50')}",
                  f"2026-10-11T23:41:00Z {SOME_RATE.format('0.50')}"]

    Scenario() \
        .given(
            the_metrics_stopped := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, the_metrics_stopped, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_RATE.format('#')} - before the metrics stopped: "
                            f"2 occurrences in 2 minutes, 23:38–23:39; # was 3.00 to 24.00, "
                            f"typically 3.00, highest at 23:38. After they stopped: "
                            f"2 occurrences in 2 minutes, 23:40–23:41; # was 0.50"])
        )


@pytest.mark.unit
def test_a_name_that_held_within_a_part_is_said_as_that_name() -> None:
    # A shopper's id varied across the group and held after the stop, where
    # "took 1 different values" counts one name instead of saying it.
    some_lines = [f"2026-10-11T23:37:00Z {SOME_SLOW_CALL.format('2300', '1-2-3', '5')}",
                  f"2026-10-11T23:38:00Z {SOME_SLOW_CALL.format('900', '4-5-6', '7')}",
                  f"2026-10-11T23:40:00Z {SOME_SLOW_CALL.format('1200', '1-2-3', '6')}"]

    Scenario() \
        .given(
            the_metrics_stopped := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, the_metrics_stopped, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{SOME_SLOW_CALL.format('#', '#-#-#', '#')} - before the metrics "
                            f"stopped: 2 occurrences in 2 minutes, 23:37–23:38; # was 900 to "
                            f"2300, typically 900, highest at 23:37; /baskets/shopper-#-#-# took "
                            f"2 different values; # was 5 to 7, typically 5, highest at 23:38. "
                            f"After they stopped: 1 occurrence in 1 minute, 23:40; # was 1200; "
                            f"/baskets/shopper-#-#-# was /baskets/shopper-1-2-3; # was 6"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("some_lines", [
    [f"2026-10-11T23:41:00Z {SOME_ERROR}", f"2026-10-11T23:43:00Z {SOME_ERROR}"],
    [f"2026-10-11T23:37:00Z {SOME_ERROR}", f"2026-10-11T23:38:00Z {SOME_ERROR}"],
    [f"2026-10-11T23:37:00Z {SOME_ERROR}", SOME_ERROR, f"2026-10-11T23:41:00Z {SOME_ERROR}"]
], ids=["only-after", "only-before", "one-line-undated"])
def test_a_message_not_logged_both_sides_of_the_stop_is_said_whole(some_lines: list[str]) -> None:
    # Two parts only where there are two sides to compare. A line with no
    # stamp belongs to neither, and a part that dropped it would miscount.
    Scenario() \
        .given(
            the_metrics_stopped := datetime(2026, 10, 11, 23, 40, tzinfo=UTC)
        ) \
        .when(
            lambda: grouped(some_lines, the_metrics_stopped, ONSET_DAY)
        ) \
        .then(
            the_answer_was(grouped(some_lines, None, ONSET_DAY))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("lines", "said"), [
    ([f"2026-10-12T00:05:00Z {SOME_ERROR}"], f"Oct 12 00:05 {SOME_ERROR}"),
    ([f"2026-10-12T00:05:00Z {SOME_ERROR}", f"2026-10-12T00:07:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 3 minutes, Oct 12 00:05–00:07"),
    ([f"2026-10-11T23:58:00Z {SOME_ERROR}", f"2026-10-12T00:04:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 7 minutes, 23:58 – Oct 12 00:04"),
    ([f"2026-10-11T23:58:00Z {SOME_RATE.format('2.5')}",
      f"2026-10-12T00:04:00Z {SOME_RATE.format('7.5')}"],
     f"{SOME_RATE.format('#')} - 2 occurrences in 7 minutes, 23:58 – Oct 12 00:04; "
     f"# was 2.5 to 7.5, typically 2.5, highest at Oct 12 00:04"),
    ([f"2026-10-12T00:05:00 {SOME_ERROR}"], f"Oct 12 00:05 {SOME_ERROR}")
], ids=["one-line", "a-span-on-one-day", "a-span-into-the-next", "its-highest-minute",
        "a-stamp-with-no-zone"])
def test_a_minute_off_the_day_the_incident_began_is_said_with_its_day(lines: list[str],
                                                                      said: str) -> None:
    # Said bare in an incident whose logs ran on another day, the model and
    # the reader both took it for a minute of the onset's day. A span on one
    # day says it once; one into the next spaces its dash, so each end is a
    # figure of its own and the second is read on its day. A stamp with no
    # zone is UTC's: read as the host's, its day was whichever the host's
    # clock put it on.
    Scenario() \
        .given(lines) \
        .when(
            lambda: [group.text for group in grouped(lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([said])
        )


@pytest.mark.unit
@pytest.mark.parametrize("lines", [
    [f"2026-10-12T00:05:00Z {SOME_ERROR}"],
    [f"2026-10-11T23:41:00Z {SOME_ERROR}", f"2026-10-11T23:43:00Z {SOME_ERROR}"],
    [SOME_ERROR]
], ids=["one-line-stamped", "several-lines", "one-line-undated"])
def test_a_group_says_where_in_its_row_the_message_it_quotes_sits(lines: list[str]) -> None:
    # The message is the one part of the row in its writer's words, so its
    # figures are read as given; everything around it is Argus's.
    Scenario() \
        .given(lines) \
        .when(
            lambda: [group.cited.text[slice(*group.quoted)]
                     for group in the_groups_of(lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([SOME_ERROR])
        )


def _label_of(message: str, groups: list[CitedEvidence]) -> str:
    return next(group.label for group in groups if message in group.text)


def _groups_say_in_order(*expected: str) -> Assertion[list[CitedEvidence]]:
    def assertion(groups: list[CitedEvidence]) -> bool:
        said = [group.text for group in groups]
        starts = [next((index for index, text in enumerate(said) if one in text), None)
                  for one in expected]

        if None in starts or starts != sorted(starts, key=lambda start: start or 0):
            raise AssertionError(f"Expected groups saying {list(expected)} in order, got {said}.")

        return True

    return assertion


def _the_same_label_twice() -> Assertion[tuple[str, str]]:
    def assertion(labels: tuple[str, str]) -> bool:
        if labels[0] != labels[1]:
            raise AssertionError(
                f"Expected one message to keep its label, got [{labels[0]}] and [{labels[1]}].")

        return True

    return assertion


def _labels_differ() -> Assertion[list[str]]:
    def assertion(labels: list[str]) -> bool:
        if len(set(labels)) != len(labels):
            raise AssertionError(f"Expected every message under a label of its own, got {labels}.")

        return True

    return assertion


def _labels_are_shaped(pattern: str) -> Assertion[list[str]]:
    def assertion(labels: list[str]) -> bool:
        misshapen = [label for label in labels if not re.fullmatch(pattern, label)]

        if misshapen:
            raise AssertionError(f"Expected labels shaped [{pattern}], got {misshapen}.")

        return True

    return assertion
