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

import pytest
from agent_postmortem.log_groups import LOG_GROUP_PREFIX, grouped
from argus_core.models import CitedEvidence
from argus_testkit import Assertion, Scenario, the_answer_was

SOME_ERROR = "ERROR io-shop: account page request failed - ZeroDivisionError at spend_summary.py:47"
SOME_RATE = "WARN io-shop: account page error rate at {}% over the last minute"


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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: [group.text for group in grouped(some_lines)]
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
            lambda: grouped(some_lines)
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
            lambda: (_label_of(SOME_ERROR, grouped(the_error_alone)),
                     _label_of(SOME_ERROR, grouped(with_another_message_first)))
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
            lambda: [group.label for group in grouped(some_lines)]
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
            lambda: [group.label for group in grouped(some_lines)]
        ) \
        .then(
            _labels_are_shaped(rf"{LOG_GROUP_PREFIX}[0-9a-f]{{4}}")
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
