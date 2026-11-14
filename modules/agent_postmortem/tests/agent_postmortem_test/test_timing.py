"""How soon after the alert each moment that went well came, and what it was,
said by code from the row the model timed it by."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_postmortem.figures import ALERT_RAISED_FIGURE, Figure
from agent_postmortem.prompting import SubmittedPostmortem
from agent_postmortem.timing import with_each_moment_timed
from argus_core import parse_iso
from argus_core.models import Lessons, TimelineEntry
from argus_testkit import Scenario, the_answer_was

# The labels of a row of the walk after the alert, one Argus said, and a
# person's line before the alert - and of rows that are not the timeline's.
SOME_RESTART, SOME_READ, SOME_MESSAGE = "T13", "T14", "XW1"
SOME_CANDIDATE, SOME_LOG_GROUP, A_ROW_NOBODY_LABELLED = "C1", "G7e5d", "T99"


def _the_instant_of(label: str) -> str:
    """The name the brief gave a row's instant, its first figure."""
    return f"{label}.1"


# The alert and each row's instant as the brief showed it - and a candidate's
# claimed instant and a log group's count, the first figures of rows that are
# not the timeline's.
SOME_FIGURES = {
    ALERT_RAISED_FIGURE: Figure(given="2026-09-02T12:00:00Z", written="12:00 UTC"),
    _the_instant_of(SOME_RESTART): Figure(given="2026-09-02T12:00:45Z", written="12:00:45 UTC"),
    _the_instant_of(SOME_READ): Figure(given="2026-09-02T12:00:50Z", written="12:00:50 UTC"),
    _the_instant_of(SOME_MESSAGE): Figure(given="2026-09-02T11:58:00Z", written="11:58 UTC"),
    _the_instant_of(SOME_CANDIDATE): Figure(given="2026-09-02T11:54:00Z", written="11:54 UTC"),
    _the_instant_of(SOME_LOG_GROUP): Figure(given="200", written="200")
}

MITIGATION = "Mitigation Agent"
ARGUS = "Argus"
# Who the narration says a thread message is by: nobody it can name.
A_PERSON = "A person"

RESTARTED = "Restarted io-pricing, a dependency of io-shop for C1"
READ_THE_FLAGS = "Read the flag provider's history - 0 flag changes"
WROTE_IN_THE_THREAD = "Wrote in the incident's thread: it's legacy-checkout-fallback"
JUDGED_REFUTED = "Judged the action REFUTED"

DONT_CARE_AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
DONT_CARE_ITEM = "dont care what the model said went well"
SOME_ITEM_LEFT_AS_WRITTEN = "Argus read the flag provider's history."

# The timeline's own rows, each as the brief and the page say it.
SOME_ROWS = {
    SOME_RESTART: TimelineEntry(at=DONT_CARE_AT, who=MITIGATION, text=RESTARTED),
    SOME_READ: TimelineEntry(at=DONT_CARE_AT, who=ARGUS, text=READ_THE_FLAGS),
    SOME_MESSAGE: TimelineEntry(at=DONT_CARE_AT, who=A_PERSON, outside_the_walk=True,
                                text=WROTE_IN_THE_THREAD)
}

# The same rows, each at the instant the figures give it: the restart before
# the read.
SOME_ROWS_IN_TIME = {
    label: SOME_ROWS[label].model_copy(
        update={"at": parse_iso(SOME_FIGURES[_the_instant_of(label)].given)})
    for label in (SOME_RESTART, SOME_READ)
}


def _an_answer_saying(*went_well: tuple[str, str | None]) -> SubmittedPostmortem:
    """An answer whose items of what went well are each timed by the row
    beside it, or by nothing."""
    return SubmittedPostmortem(lessons=Lessons(went_well=[item for item, _ in went_well]),
                               went_well_timed_by=[row for _, row in went_well])


def _after_the_alert(label: str) -> str:
    """The span from the alert to a row, as code names it for the figures."""
    return f"{{{_the_instant_of(label)} - {ALERT_RAISED_FIGURE}}} after the alert was raised"


def _the_moments_of(answer: SubmittedPostmortem) -> tuple[Lessons | None, list[str | None] | None]:
    """What went well, and the row each item is timed by, in the answer's order."""
    return answer.lessons, answer.went_well_timed_by


def _lowered(line: str) -> str:
    return line[:1].lower() + line[1:]


@pytest.mark.unit
def test_a_timed_item_is_said_as_its_row_says_it() -> None:
    # Timed by the restart, the item went on to the confirmation three minutes
    # later, and the span dated both to the restart. Said as the row, the span
    # times exactly what the row did.
    Scenario() \
        .given(
            an_answer := _an_answer_saying(("The Mitigation Agent restarted io-pricing, and "
                                            "the action was confirmed.", SOME_RESTART))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES, SOME_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{_after_the_alert(SOME_RESTART)}, the {MITIGATION} {_lowered(RESTARTED)}."]))
        )


@pytest.mark.unit
def test_moments_said_as_their_rows_come_in_the_order_they_happened() -> None:
    # Listed later-first, the spans down the page ran backwards in time. An
    # item left as a sentence keeps its place between them.
    Scenario() \
        .given(
            an_answer := _an_answer_saying((DONT_CARE_ITEM, SOME_READ),
                                           (SOME_ITEM_LEFT_AS_WRITTEN, None),
                                           (DONT_CARE_ITEM, SOME_RESTART))
        ) \
        .when(
            lambda: _the_moments_of(with_each_moment_timed(an_answer, SOME_FIGURES,
                                                           SOME_ROWS_IN_TIME))
        ) \
        .then(
            the_answer_was((
                Lessons(went_well=[
                    f"{_after_the_alert(SOME_RESTART)}, the {MITIGATION} {_lowered(RESTARTED)}.",
                    SOME_ITEM_LEFT_AS_WRITTEN,
                    f"{_after_the_alert(SOME_READ)}, {ARGUS} {_lowered(READ_THE_FLAGS)}."]),
                [SOME_RESTART, None, SOME_READ]))
        )


@pytest.mark.unit
def test_an_item_timed_by_a_refuted_verdict_says_only_what_its_undo_did() -> None:
    # Every write-up timing an item by a refuted verdict's row credited the
    # put-back, and the row said whole credited the verdict too - beside a
    # went_wrong item faulting that verdict, so the page praised and faulted
    # one thing.
    some_put_back = "monthly-spend-feature was put back ON"
    a_refuted_verdict = TimelineEntry(at=DONT_CARE_AT, who=MITIGATION,
                                      text=f"{JUDGED_REFUTED} - {some_put_back}",
                                      put_back=some_put_back)

    Scenario() \
        .given(
            an_answer := _an_answer_saying((DONT_CARE_ITEM, SOME_RESTART))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES,
                                           {SOME_RESTART: a_refuted_verdict}).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{_after_the_alert(SOME_RESTART)}, {some_put_back}."]))
        )


@pytest.mark.unit
def test_a_row_argus_said_takes_no_article() -> None:
    Scenario() \
        .given(
            an_answer := _an_answer_saying((DONT_CARE_ITEM, SOME_READ))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES, SOME_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{_after_the_alert(SOME_READ)}, {ARGUS} {_lowered(READ_THE_FLAGS)}."]))
        )


@pytest.mark.unit
def test_a_thread_message_before_the_alert_is_said_as_a_person_s() -> None:
    # A person can write before the alert fires; a span worked the other way
    # round comes out below nothing. The narration names nobody for a thread
    # message, and "A person" mid-sentence is "a person".
    Scenario() \
        .given(
            an_answer := _an_answer_saying((DONT_CARE_ITEM, SOME_MESSAGE))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES, SOME_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[
                f"{{{ALERT_RAISED_FIGURE} - {_the_instant_of(SOME_MESSAGE)}}} before the alert "
                f"was raised, {_lowered(A_PERSON)} {_lowered(WROTE_IN_THE_THREAD)}."]))
        )


@pytest.mark.unit
@pytest.mark.parametrize("timed_by", [None, A_ROW_NOBODY_LABELLED, SOME_CANDIDATE, SOME_LOG_GROUP],
                         ids=["timed-by-nothing", "a-row-with-no-instant",
                              "a-candidate-s-claimed-instant", "a-log-group-s-count"])
def test_an_item_with_no_row_of_the_timeline_to_time_it_by_is_left_as_written(
        timed_by: str | None) -> None:
    # Any other row is the check's to send back. A candidate's first figure is
    # the instant it claims, and timed by it an item said when nothing was done;
    # a log group's is a count, which no span is worked out from.
    Scenario() \
        .given(
            an_answer := _an_answer_saying((SOME_ITEM_LEFT_AS_WRITTEN, timed_by))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES, SOME_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=[SOME_ITEM_LEFT_AS_WRITTEN]))
        )


@pytest.mark.unit
def test_what_went_well_sent_as_sentences_is_left_as_written() -> None:
    # The shape answers recorded before rows were asked for came in.
    some_items = ["THE FIRST", "THE SECOND"]

    Scenario() \
        .given(
            an_answer := SubmittedPostmortem(lessons=Lessons(went_well=some_items))
        ) \
        .when(
            lambda: with_each_moment_timed(an_answer, SOME_FIGURES, SOME_ROWS).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=some_items))
        )
