"""How soon after the alert each moment that went well came, said by code."""

from __future__ import annotations

import pytest
from agent_postmortem.figures import ALERT_RAISED_FIGURE, Figure
from agent_postmortem.prompting import SubmittedPostmortem
from agent_postmortem.timing import with_each_moment_timed
from argus_core.models import Lessons
from argus_testkit import Scenario, the_answer_was

# The alert, a row of the walk after it and a person's line before it, each as
# the brief showed its instant - and a candidate's claimed instant and a log
# group's count, the first figures of rows that are not the timeline's.
SOME_FIGURES = {
    ALERT_RAISED_FIGURE: Figure(given="2026-09-02T12:00:00Z", written="12:00 UTC"),
    "T13.1": Figure(given="2026-09-02T12:00:45Z", written="12:00:45 UTC"),
    "XW1.1": Figure(given="2026-09-02T11:58:00Z", written="11:58 UTC"),
    "C1.1": Figure(given="2026-09-02T11:54:00Z", written="11:54 UTC"),
    "G7e5d.1": Figure(given="200", written="200")
}

# The timeline's own rows.
SOME_TIMELINE_ROWS = frozenset({"T13", "XW1"})


def _an_answer_saying(*went_well: tuple[str, str | None]) -> SubmittedPostmortem:
    """An answer whose items of what went well are each timed by the row
    beside it, or by nothing."""
    return SubmittedPostmortem(lessons=Lessons(went_well=[item for item, _ in went_well]),
                               went_well_timed_by=[row for _, row in went_well])


@pytest.mark.unit
def test_an_item_timed_by_a_row_is_said_after_how_long_from_the_alert_that_row_came() -> None:
    # Set by the model, the confirmation's span came after "brought the
    # service back", so it read as a three-minute recovery from a service back
    # in one. Said first, the span times the whole item; the article it opened
    # with is lowered as the sentence goes on.
    Scenario() \
        .when(
            lambda: with_each_moment_timed(
                _an_answer_saying(("The Investigator Agent formed C1.", "T13")), SOME_FIGURES,
                SOME_TIMELINE_ROWS)
            .lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{{T13.1 - {ALERT_RAISED_FIGURE}}} after the alert was raised, the "
                f"Investigator Agent formed C1."]))
        )


@pytest.mark.unit
def test_an_item_timed_by_a_row_before_the_alert_is_said_before_it() -> None:
    # A person can write before the alert fires; a span worked the other way
    # round comes out below nothing.
    Scenario() \
        .when(
            lambda: with_each_moment_timed(
                _an_answer_saying(("Argus took the report in", "XW1")), SOME_FIGURES,
                SOME_TIMELINE_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{{{ALERT_RAISED_FIGURE} - XW1.1}} before the alert was raised, Argus took "
                f"the report in."]))
        )


@pytest.mark.unit
@pytest.mark.parametrize("went_well", [
    [("Argus read the flag provider's history.", None)],
    [("Argus read the flag provider's history.", "T99")],
    [("Argus read the flag provider's history.", "C1")],
    [("Argus read the flag provider's history.", "G7e5d")]
], ids=["timed-by-nothing", "a-row-with-no-instant", "a-candidate-s-claimed-instant",
        "a-log-group-s-count"])
def test_an_item_with_no_row_of_the_timeline_to_time_it_by_is_left_as_written(
        went_well: list[tuple[str, str | None]]) -> None:
    # Any other row is the check's to send back. A candidate's first figure is
    # the instant it claims, and timed by it an item said when nothing was done;
    # a log group's is a count, which no span is worked out from.
    Scenario() \
        .when(
            lambda: with_each_moment_timed(_an_answer_saying(*went_well), SOME_FIGURES,
                                           SOME_TIMELINE_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=["Argus read the flag provider's history."]))
        )


@pytest.mark.unit
def test_what_went_well_sent_as_sentences_is_left_as_written() -> None:
    # The shape answers recorded before rows were asked for came in.
    Scenario() \
        .when(
            lambda: with_each_moment_timed(
                SubmittedPostmortem(lessons=Lessons(went_well=["THE FIRST", "THE SECOND"])),
                SOME_FIGURES, SOME_TIMELINE_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=["THE FIRST", "THE SECOND"]))
        )
