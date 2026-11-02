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
from datetime import UTC, date, datetime, timedelta

import pytest
from agent_postmortem.figures import the_log_group_figures
from agent_postmortem.log_groups import (
    LOG_GROUP_PREFIX,
    LogGroup,
    grouped,
    labels_reaching_into,
    the_groups_of,
)
from argus_core import to_iso
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
            the_answer_was([f"{SOME_ERROR} - 2 occurrences in 3 minutes, 23:59–00:01"])
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
                            f"23:37–23:39; # was 1.50% to 24.00%, typically 3.00%, "
                            f"highest at 23:38"])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("message", "said"), [
    ("WARN io-shop: account page error rate at {}% over the last minute",
     "# was 1.50% to 24.00%, typically 3.00%"),
    ("WARN io-shop: slow upstream call took {}ms",
     "# was 1.50ms to 24.00ms, typically 3.00ms"),
    ("WARN io-shop: account page error rate at {}%.",
     "# was 1.50% to 24.00%, typically 3.00%"),
    ("WARN io-shop: {} requests queued",
     "# was 1.50 to 24.00, typically 3.00")
], ids=["a-percentage", "a-unit-in-letters", "a-unit-before-a-full-stop", "no-unit"])
def test_a_number_that_varied_is_said_with_the_unit_its_message_writes_after_it(
        message: str, said: str) -> None:
    # Handed a rate logged as "36.50%" as "# was 0.50 to 36.50", a write-up said
    # the account page error rate was "as high as 36.00". The unit is the rest
    # of the number's word; the punctuation closing the word is no part of it.
    Scenario() \
        .given(
            some_lines := [f"2026-10-11T23:37:00Z {message.format('1.50')}",
                           f"2026-10-11T23:38:00Z {message.format('24.00')}",
                           f"2026-10-11T23:39:00Z {message.format('3.00')}"]
        ) \
        .when(
            lambda: [group.text for group in grouped(some_lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([f"{message.format('#')} - 3 occurrences in 3 minutes, "
                            f"23:37–23:39; {said}, highest at 23:38"])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("lines", "said"), [
    ([f"2026-10-11T23:36:00Z {SOME_ERROR}"], f"{SOME_ERROR} - 1 occurrence in 1 minute, 23:36"),
    ([SOME_ERROR], f"{SOME_ERROR} - 1 occurrence")
], ids=["stamped", "undated"])
def test_a_message_logged_once_is_said_as_any_other_with_how_often_and_over_how_long(
        lines: list[str], said: str) -> None:
    # Led by its minute, a line logged once read as saying what held from then
    # on: handed "12:30 ... off 103 / on 97 - 200 evaluations", write-ups gave
    # 97 of 200 as how far a flag reached, though every evaluation after that
    # minute was on. Said as every other message is, it holds for its one
    # minute and no longer.
    Scenario() \
        .given(lines) \
        .when(
            lambda: [group.text for group in grouped(lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([said])
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
                            f"3 minutes, 23:37–23:39; # was 900ms to 2300ms, typically 1200ms, "
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
                            f"3 occurrences in 3 minutes, 23:37–23:39; # was 1.50% to 24.00%, "
                            f"typically 3.00%, highest at 23:38. After they stopped: "
                            f"2 occurrences in 2 minutes, 23:40–23:41; # was 0.50% to 1.00%, "
                            f"typically 0.50%, highest at 23:41"])
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
                            f"2 occurrences in 2 minutes, 23:38–23:39; # was 3.00% to 24.00%, "
                            f"typically 3.00%, highest at 23:38. After they stopped: "
                            f"1 occurrence in 1 minute, 23:40; # was 0.50%"])
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
                            f"2 occurrences in 2 minutes, 23:38–23:39; # was 3.00% to 24.00%, "
                            f"typically 3.00%, highest at 23:38. After they stopped: "
                            f"2 occurrences in 2 minutes, 23:40–23:41; # was 0.50%"])
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
                            f"stopped: 2 occurrences in 2 minutes, 23:37–23:38; # was 900ms to "
                            f"2300ms, typically 900ms, highest at 23:37; /baskets/shopper-#-#-# "
                            f"took 2 different values; # was 5 to 7, typically 5, highest at "
                            f"23:38. After they stopped: 1 occurrence in 1 minute, 23:40; "
                            f"# was 1200ms; "
                            f"/baskets/shopper-#-#-# was /baskets/shopper-1-2-3; # was 6"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("some_lines", [
    [f"2026-10-11T23:41:00Z {SOME_ERROR}", f"2026-10-11T23:43:00Z {SOME_ERROR}"],
    [f"2026-10-11T23:37:00Z {SOME_ERROR}", f"2026-10-11T23:38:00Z {SOME_ERROR}"],
    [f"2026-10-11T23:37:00Z {SOME_ERROR}", SOME_ERROR, f"2026-10-11T23:41:00Z {SOME_ERROR}"]
], ids=["only-after", "only-before", "both-sides-one-undated"])
def test_a_message_is_said_whole_unless_all_its_lines_are_dated_and_fall_both_sides_of_the_stop(
        some_lines: list[str]) -> None:
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
    ([f"2026-10-12T00:05:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 1 occurrence in 1 minute, Oct 12 00:05"),
    ([f"2026-10-12T00:05:00Z {SOME_ERROR}", f"2026-10-12T00:07:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 3 minutes, Oct 12 00:05–00:07"),
    ([f"2026-10-11T23:58:00Z {SOME_ERROR}", f"2026-10-12T00:04:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 7 minutes, 23:58–00:04"),
    ([f"2026-10-12T23:58:00Z {SOME_ERROR}", f"2026-10-13T00:04:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 7 minutes, Oct 12 23:58–00:04"),
    ([f"2026-10-11T23:58:00Z {SOME_RATE.format('2.5')}",
      f"2026-10-12T00:04:00Z {SOME_RATE.format('7.5')}"],
     f"{SOME_RATE.format('#')} - 2 occurrences in 7 minutes, 23:58–00:04; "
     f"# was 2.5% to 7.5%, typically 2.5%, highest at Oct 12 00:04"),
    ([f"2026-10-11T23:58:00Z {SOME_ERROR}", f"2026-10-12T23:57:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 1440 minutes, 23:58–23:57"),
    ([f"2026-10-11T23:58:00Z {SOME_ERROR}", f"2026-10-12T23:58:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 1441 minutes, 23:58 – Oct 12 23:58"),
    ([f"2026-10-11T23:58:00Z {SOME_ERROR}", f"2026-10-14T00:04:00Z {SOME_ERROR}"],
     f"{SOME_ERROR} - 2 occurrences in 2887 minutes, 23:58 – Oct 14 00:04"),
    ([f"2026-10-12T00:05:00 {SOME_ERROR}"],
     f"{SOME_ERROR} - 1 occurrence in 1 minute, Oct 12 00:05")
], ids=["one-line", "a-span-on-one-day", "a-span-into-the-next", "a-span-from-a-later-day",
        "its-highest-minute", "a-day-less-a-minute", "a-day-to-the-minute", "days",
        "a-stamp-with-no-zone"])
def test_a_minute_off_the_day_the_incident_began_is_said_with_its_day(lines: list[str],
                                                                      said: str) -> None:
    # Said bare in an incident whose logs ran on another day, the model and
    # the reader both took it for a minute of the onset's day. A span shorter
    # than a day is one figure wherever midnight falls, its first day said
    # once: spaced into two where it crossed midnight, a replay run across
    # midnight named every figure after it one place on from the daytime run
    # its answer was recorded in: "peaked at 0.5%" of a rate whose peak was
    # 36%. A day or more spaces its dash, so each end is
    # read on its own day - two figures in every run. A stamp with no zone is
    # UTC's: read as the host's, its day was whichever the host's clock put
    # it on.
    Scenario() \
        .given(lines) \
        .when(
            lambda: [group.text for group in grouped(lines, None, ONSET_DAY)]
        ) \
        .then(
            the_answer_was([said])
        )


@pytest.mark.unit
@pytest.mark.parametrize("first_minute", [
    datetime(2026, 10, 11, 14, 11, tzinfo=UTC),
    datetime(2026, 10, 11, 23, 51, tzinfo=UTC)
], ids=["by-day", "across-midnight"])
def test_a_group_names_its_figures_alike_wherever_midnight_falls(first_minute: datetime) -> None:
    # An answer recorded in a daytime run is replayed in runs across
    # midnight, and cites a group's figures by their place. With the span two
    # figures there, every one after it moved a place: "peaked at 0.5%" of a
    # rate whose peak was 36%.
    some_lines = [f"{to_iso(first_minute + timedelta(minutes=minute))} "
                  f"{SOME_RATE.format(rate)}"
                  for minute, rate in ((0, "0.50"), (18, "36.00"), (37, "2.00"))]

    Scenario() \
        .given(some_lines) \
        .when(
            lambda: the_groups_of(some_lines, None, ONSET_DAY)
        ) \
        .then(
            _its_figure(5, "36%")
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


def _its_figure(place: int, expected: str) -> Assertion[list[LogGroup]]:
    def assertion(groups: list[LogGroup]) -> bool:
        group = groups[0]
        name = f"{group.cited.label}.{place}"
        figures = the_log_group_figures([(group.cited, group.quoted)], ONSET_DAY)

        if name not in figures or figures[name].written != expected:
            raise AssertionError(f"Expected [{name}] of [{group.cited.text}] written in as "
                                 f"[{expected}], and it was "
                                 f"[{figures[name].written if name in figures else 'no figure'}].")

        return True

    return assertion


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
