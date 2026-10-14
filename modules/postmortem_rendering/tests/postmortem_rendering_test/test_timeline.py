"""The incident in order: every line of its narration in UTC, with the four
markers Argus placed - the date said where the day changes, and only there.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import TimelineEntry, TimelineMarker
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.timeline import TimelineRow, the_timeline

from postmortem_rendering_test.framework.builders import a_postmortem

SOME_MOMENT = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)


@pytest.mark.unit
def test_a_line_carries_its_time_its_marker_who_said_it_and_the_narration() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                TimelineEntry(at=SOME_MOMENT, who="Investigator Agent",
                              text="the service began to fail",
                              marker=TimelineMarker.IMPACT_BEGINS, label="E1")])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows
        ) \
        .then(
            the_answer_was((TimelineRow(label="E1", at="Oct 11 14:03:00",
                                        marker="IMPACT BEGINS", who="Investigator Agent",
                                        text=Line(runs=(Run(text="the service began to fail",
                                                            role=Role.NARRATION),))),)))


@pytest.mark.unit
def test_the_date_is_said_where_the_day_changes_and_only_there() -> None:
    # A time of day alone reads in order within one day; an incident spanning
    # days would read as time running backwards.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                TimelineEntry(at=SOME_MOMENT, who=None, text="dont care"),
                TimelineEntry(at=SOME_MOMENT + timedelta(minutes=1), who=None, text="dont care"),
                TimelineEntry(at=SOME_MOMENT + timedelta(days=1), who=None, text="dont care")])
        ) \
        .when(
            lambda: tuple(row.at for row in the_timeline(some_postmortem).rows)
        ) \
        .then(
            the_answer_was(("Oct 11 14:03:00", "14:04:00", "Oct 12 14:03:00")))


@pytest.mark.unit
def test_a_line_without_a_marker_or_a_speaker_carries_neither() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                TimelineEntry(at=SOME_MOMENT, who=None, text="dont care")])
        ) \
        .when(
            lambda: (the_timeline(some_postmortem).rows[0].marker,
                     the_timeline(some_postmortem).rows[0].who)
        ) \
        .then(
            the_answer_was((None, None)))


@pytest.mark.unit
def test_the_timeline_says_its_zone_once() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_timeline(dont_care_postmortem).zone
        ) \
        .then(
            the_answer_was("(UTC)"))


@pytest.mark.unit
def test_no_timeline_says_none_was_recorded() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).absent
        ) \
        .then(
            the_answer_was("No timeline was recorded."))
