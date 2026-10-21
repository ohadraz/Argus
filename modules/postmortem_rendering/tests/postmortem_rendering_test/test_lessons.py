"""What was learned, in three lists: what went well, what went wrong, and where
the incident got lucky - each present, empty or not.

And the lesson on detection, which code writes from what was measured: first in
the list it belongs in, in words worked out here rather than the model's.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from argus_core.models import DetectionLesson, DetectionMeasuredFrom, Lessons
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.lessons import LessonList, the_lessons
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_the_three_lists_arrive_in_order_each_under_its_heading() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(lessons=Lessons(
                went_well=["the alert fired within minutes"],
                went_wrong=["no test exercised an empty month"],
                got_lucky=["the fault was behind a flag"]))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)
        ) \
        .then(
            the_answer_was((
                LessonList(heading="What went well",
                           items=(Line(runs=(Run(text="the alert fired within minutes",
                                                 role=Role.PROSE),)),),
                           absent=None),
                LessonList(heading="What went wrong",
                           items=(Line(runs=(Run(text="no test exercised an empty month",
                                                 role=Role.PROSE),)),),
                           absent=None),
                LessonList(heading="Where it got lucky",
                           items=(Line(runs=(Run(text="the fault was behind a flag",
                                                 role=Role.PROSE),)),),
                           absent=None))))


@pytest.mark.unit
def test_an_empty_list_says_nothing_was_in_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(lessons=Lessons(went_well=["dont care"],
                                                            went_wrong=["dont care"],
                                                            got_lucky=[]))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)[2].absent
        ) \
        .then(
            the_answer_was("Nothing."))


@pytest.mark.unit
def test_a_document_with_no_lessons_still_has_all_three_lists() -> None:
    # A missing heading reads as one nobody thought to write.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(lessons=None)
        ) \
        .when(
            lambda: tuple(lessons.absent for lessons in the_lessons(some_postmortem))
        ) \
        .then(
            the_answer_was(("Nothing.", "Nothing.", "Nothing.")))


@pytest.mark.unit
def test_an_alert_within_what_was_accounted_for_is_said_first_under_what_went_well() -> None:
    # Plain, not prose: the words are worked out here, not the model's. The
    # time to scrape and store is an allowance nobody measured, and said as
    # the rule's own parts are it would read as a fact about the stack.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                lessons=Lessons(went_well=["the logs told the gap apart"]),
                detection_lesson=DetectionLesson(
                    gap=timedelta(minutes=5, seconds=53),
                    measured_from=DetectionMeasuredFrom.ONSET,
                    rule_waits=timedelta(0),
                    rule_looks_back=timedelta(minutes=5),
                    rule_evaluated_every=timedelta(minutes=1),
                    scraping_and_storing=timedelta(seconds=30)))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)[0].items
        ) \
        .then(
            the_answer_was((
                Line(runs=(Run(text="The alert came 5 minutes 53 seconds after the onset, "
                                    "within the 7 minutes 30 seconds accounted for by its "
                                    "condition looking back over 5 minutes, its evaluation at "
                                    "intervals of 1 minute, an unmeasured allowance of 30 "
                                    "seconds for scraping and storing its samples and the "
                                    "whole minute the onset is measured to."),)),
                Line(runs=(Run(text="the logs told the gap apart", role=Role.PROSE),))))
        )


@pytest.mark.unit
def test_an_alert_later_than_what_was_accounted_for_is_said_first_under_what_went_wrong(
) -> None:
    # A part of nothing is left out: a condition looking back over no range
    # spends no time.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                lessons=Lessons(went_wrong=["the draft waits on a person"]),
                detection_lesson=DetectionLesson(
                    gap=timedelta(minutes=12),
                    measured_from=DetectionMeasuredFrom.LINE_PASSED,
                    rule_waits=timedelta(minutes=2),
                    rule_looks_back=timedelta(0),
                    rule_evaluated_every=timedelta(seconds=30),
                    scraping_and_storing=timedelta(seconds=30)))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)[1].items
        ) \
        .then(
            the_answer_was((
                Line(runs=(Run(text="The alert came 12 minutes after its series passed its "
                                    "line, 8 minutes more than the 4 minutes accounted for by "
                                    "its rule waiting 2 minutes with its condition holding, "
                                    "its evaluation at intervals of 30 seconds, an "
                                    "unmeasured allowance of 30 seconds for scraping and "
                                    "storing its samples and the whole minute its series is "
                                    "read in."),)),
                Line(runs=(Run(text="the draft waits on a person", role=Role.PROSE),))))
        )


@pytest.mark.unit
def test_where_the_metrics_stopped_at_the_onset_the_alert_is_said_after_their_stopping(
) -> None:
    # What the onset dates there is the metrics stopping, and the service may
    # have gone on serving as before.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection_lesson=DetectionLesson(
                gap=timedelta(minutes=5),
                measured_from=DetectionMeasuredFrom.METRICS_STOPPED,
                rule_waits=timedelta(0),
                rule_looks_back=timedelta(minutes=5),
                rule_evaluated_every=timedelta(minutes=1),
                scraping_and_storing=timedelta(seconds=30)))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)
        ) \
        .then(
            _the_lesson_says(0, "The alert came 5 minutes after the metrics stopped",
                             "the whole minute the metrics' stopping is measured to.")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("gap", "listed_under"), [
    (timedelta(minutes=7, seconds=30), 0),
    (timedelta(minutes=7, seconds=31), 1)
], ids=["exactly-what-was-accounted-for", "a-second-more"])
def test_detection_went_wrong_from_the_first_second_past_what_was_accounted_for(
        gap: timedelta, listed_under: int) -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection_lesson=DetectionLesson(
                gap=gap,
                measured_from=DetectionMeasuredFrom.ONSET,
                rule_waits=timedelta(0),
                rule_looks_back=timedelta(minutes=5),
                rule_evaluated_every=timedelta(minutes=1),
                scraping_and_storing=timedelta(seconds=30)))
        ) \
        .when(
            lambda: the_lessons(some_postmortem)
        ) \
        .then(
            _the_lesson_says(listed_under, "The alert came")
        )


def _the_lesson_says(listed_under: int, *parts: str) -> Assertion[tuple[LessonList, ...]]:
    """The detection lesson, alone in the list at `listed_under`, saying each of
    `parts`."""
    def assertion(lists: tuple[LessonList, ...]) -> bool:
        listed = [(position, " ".join(run.text for run in item.runs))
                  for position, each in enumerate(lists) for item in each.items]
        if (len(listed) != 1 or listed[0][0] != listed_under
                or any(part not in listed[0][1] for part in parts)):
            raise AssertionError(
                f"Expected one lesson, in list {listed_under}, saying {list(parts)}, got "
                f"{listed}.")

        return True

    return assertion
