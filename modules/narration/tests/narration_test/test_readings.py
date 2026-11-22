"""What came of reading a channel that left nothing to list, said as every place
showing it says it."""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import ChangeKind, ChannelReading
from narration import changes_not_listed, no_logs_listed

# What is said of each reading, as a clause after the kind of change it was.
HOW_EACH_READING_IS_SAID = [
    (ChannelReading.READ, "read, none came back"),
    (ChannelReading.ONLY_SINCE_ARGUS_ACTED,
     "read, only changes made since Argus first acted came back"),
    (ChannelReading.NOT_ASKED, "not read"),
    (ChannelReading.UNANSWERED, "asked for, no answer came back")
]

DONT_CARE_READING = ChannelReading.READ


@pytest.mark.parametrize(("reading", "said"), HOW_EACH_READING_IS_SAID)
@pytest.mark.unit
def test_deploys_with_no_row_are_said_by_what_came_of_reading_them(
        reading: ChannelReading, said: str) -> None:
    # Said whatever the flags hold: a list of flag toggles says nothing of the
    # deploys, and its reader takes them as read when nobody asked for them.
    Scenario() \
        .when(
            lambda: changes_not_listed(reading, DONT_CARE_READING, {ChangeKind.FLAG_TOGGLE})
        ) \
        .then(
            the_answer_was(f"Deploys {said}.")
        )


@pytest.mark.parametrize(("reading", "said"), HOW_EACH_READING_IS_SAID)
@pytest.mark.unit
def test_flags_with_no_row_are_said_by_what_came_of_reading_them(
        reading: ChannelReading, said: str) -> None:
    Scenario() \
        .when(
            lambda: changes_not_listed(DONT_CARE_READING, reading, {ChangeKind.DEPLOY})
        ) \
        .then(
            the_answer_was(f"Flags {said}.")
        )


@pytest.mark.unit
def test_each_kind_with_no_row_is_said_apart() -> None:
    # One word for both would say the deploys were read whenever the flags were,
    # and the walk reads the flags every time and the deploys only when asked.
    Scenario() \
        .when(
            lambda: changes_not_listed(ChannelReading.NOT_ASKED, ChannelReading.READ, set())
        ) \
        .then(
            the_answer_was("Deploys not read; flags read, none came back.")
        )


@pytest.mark.unit
def test_nothing_is_said_where_both_kinds_have_rows() -> None:
    Scenario() \
        .when(
            lambda: changes_not_listed(DONT_CARE_READING, DONT_CARE_READING,
                                       {ChangeKind.DEPLOY, ChangeKind.FLAG_TOGGLE})
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.parametrize(("reading", "said"), [
    (ChannelReading.READ, "Read; none came back."),
    (ChannelReading.ONLY_SINCE_ARGUS_ACTED, "Read; none came back."),
    (ChannelReading.NOT_ASKED, "Not read."),
    (ChannelReading.UNANSWERED, "Asked for; no answer came back.")
])
@pytest.mark.unit
def test_no_log_message_listed_is_said_by_what_came_of_reading_the_logs(
        reading: ChannelReading, said: str) -> None:
    Scenario() \
        .when(
            lambda: no_logs_listed(reading)
        ) \
        .then(
            the_answer_was(said)
        )
