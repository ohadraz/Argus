"""What was learned, in three lists: what went well, what went wrong, and where
the incident got lucky - each present, empty or not.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

import pytest
from argus_core.models import Lessons
from argus_testkit import Scenario, the_answer_was
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
