"""The incident in order: every line of its narration in UTC, with the four
markers Argus placed - the date said where the day changes, and only there.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import HypothesisConsidered, TimelineEntry, TimelineMarker
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.timeline import TimelineRow, the_timeline

from postmortem_rendering_test.framework.builders import (
    SOME_DEPLOYED_REVISION,
    SOME_REPOSITORY_ADDRESS,
    a_deploy_read,
    a_postmortem,
)

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
def test_a_line_naming_the_candidates_it_formed_cites_each_one_s_row() -> None:
    # "Formed 2 candidate causes, best first: C1, C2" is a list of rows the
    # document shows under those labels, and a reader follows each one there.
    # C3 has no row in this document, so it stays words.
    some_hypotheses = [HypothesisConsidered(summary="dont care", confidence=None,
                                            result="dont care", label=label)
                       for label in ("C1", "C2")]

    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                hypotheses=some_hypotheses,
                timeline=[TimelineEntry(at=SOME_MOMENT, who="Investigator Agent",
                                        text="Formed 3 candidate causes, best first: C1, C2, C3",
                                        label="T1")])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="Formed 3 candidate causes, best first: ", role=Role.NARRATION),
                Run(text="C1", role=Role.CITATION, address="C1"),
                Run(text=", ", role=Role.NARRATION),
                Run(text="C2", role=Role.CITATION, address="C2"),
                Run(text=", C3", role=Role.NARRATION)))))


@pytest.mark.unit
def test_a_candidate_the_line_names_by_a_label_its_row_also_goes_by_cites_that_row() -> None:
    # C2 is one cause with C1, and shown on C1's row - which goes by both, so
    # the line forming them still leads a reader from each.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="dont care", label="C1", also=["C2"])],
                timeline=[TimelineEntry(at=SOME_MOMENT, who="Investigator Agent",
                                        text="Formed 2 candidate causes, best first: C1, C2",
                                        label="T1")])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="Formed 2 candidate causes, best first: ", role=Role.NARRATION),
                Run(text="C1", role=Role.CITATION, address="C1"),
                Run(text=", ", role=Role.NARRATION),
                Run(text="C2", role=Role.CITATION, address="C2")))))


@pytest.mark.unit
def test_a_revision_a_line_names_whole_is_said_short_and_leads_where_it_opens() -> None:
    # The record keeps a revision whole, and the document writes one short
    # wherever it names it - the prose, the changes read - so a line of the
    # timeline names it the same way, and a reader opens it from there.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[a_deploy_read("P2")],
                timeline=[TimelineEntry(
                    at=SOME_MOMENT, who="Argus",
                    text=f"rolled [io-shop] back off revision [{SOME_DEPLOYED_REVISION}]",
                    label="T1")])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="rolled io-shop back off revision ", role=Role.NARRATION),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK, address=commit)))))


@pytest.mark.unit
def test_a_revision_a_line_names_by_a_start_of_it_is_said_short_and_leads_where_it_opens() -> None:
    # The model names a revision by as much of it as it likes - eight
    # characters, often - and a candidate's line says it as the model wrote it.
    # Left so, one document names one revision two ways, and only one opens.
    commit = f"{SOME_REPOSITORY_ADDRESS}/commit/{SOME_DEPLOYED_REVISION}"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[a_deploy_read("P2")],
                timeline=[TimelineEntry(
                    at=SOME_MOMENT, who="Investigator Agent",
                    text=f"Moving on to [{SOME_DEPLOYED_REVISION[:8]}] made every page slow",
                    label="T1")])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(
                Run(text="Moving on to ", role=Role.NARRATION),
                Run(text=SOME_DEPLOYED_REVISION[:7], role=Role.LINK, address=commit),
                Run(text=" made every page slow", role=Role.NARRATION)))))


@pytest.mark.unit
def test_a_line_a_person_wrote_keeps_its_brackets() -> None:
    # The walk's brackets quote a name for the model and are left off where a
    # line is shown; a person's are theirs.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                TimelineEntry(at=SOME_MOMENT, who="kuki", text="the [checkout] flag again?",
                              label="XW1", outside_the_walk=True)])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="the [checkout] flag again?",
                                          role=Role.NARRATION),))))


@pytest.mark.unit
def test_a_revision_a_person_wrote_is_said_as_they_wrote_it() -> None:
    # As the dashboard and the channel say it: a person's words are theirs,
    # a revision they wrote whole among them.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[a_deploy_read("P2")],
                timeline=[TimelineEntry(at=SOME_MOMENT, who="kuki",
                                        text=f"was it {SOME_DEPLOYED_REVISION}?",
                                        label="XW1", outside_the_walk=True)])
        ) \
        .when(
            lambda: the_timeline(some_postmortem).rows[0].text
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text=f"was it {SOME_DEPLOYED_REVISION}?",
                                          role=Role.NARRATION),))))


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
