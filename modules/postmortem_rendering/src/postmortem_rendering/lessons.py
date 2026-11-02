"""What was learned, in three lists: what went well, what went wrong, and where
the incident got lucky - each present, empty or not, so a reader weighs one
against the others.

And the lesson on detection, which code writes from what was measured: said
here as the brief says it (`argus_core.models.the_detection_lesson_said`),
first in the list it belongs in - within what the rule spends before it can
fire, it went well; beyond it, wrong by the rest.
"""

from __future__ import annotations

from typing import Final

from argus_core import said_as_a_span
from argus_core.models import (
    DetectionLesson,
    PostmortemDocument,
    the_detection_lesson_said,
    within_what_was_accounted_for,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run

_NOTHING: Final = "Nothing."


class LessonList(BaseModel):
    """One list under its heading, and the word said in its place where it is
    empty - `None` where it is not."""

    model_config = ConfigDict(frozen=True)

    heading: str
    items: tuple[Line, ...]
    absent: str | None


def the_lessons(postmortem: PostmortemDocument) -> tuple[LessonList, ...]:
    """The three lists in Google's order, each of the model's lessons a line of
    prose - and the lesson on detection, where there is one, first in its list
    as a plain line."""
    lessons = postmortem.lessons
    detection = postmortem.detection_lesson
    went_well = detection is not None and within_what_was_accounted_for(detection)
    said = (("What went well",
             (_said(detection),) if detection and went_well else (),
             lessons.went_well if lessons else []),
            ("What went wrong",
             (_said(detection),) if detection and not went_well else (),
             lessons.went_wrong if lessons else []),
            ("Where it got lucky", (), lessons.got_lucky if lessons else []))

    return tuple(LessonList(heading=heading,
                            items=(*written,
                                   *(Line(runs=(Run(text=lesson, role=Role.PROSE),))
                                     for lesson in listed)),
                            absent=None if written or listed else _NOTHING)
                 for heading, written, listed in said)


def _said(lesson: DetectionLesson) -> Line:
    """The lesson as one sentence, each span said as the page says one."""
    return Line(runs=(Run(text=the_detection_lesson_said(
        lesson, lambda _, span: said_as_a_span(span))),))
