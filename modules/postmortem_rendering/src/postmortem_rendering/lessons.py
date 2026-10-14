"""What was learned, in three lists: what went well, what went wrong, and where
the incident got lucky - each present, empty or not, so a reader weighs one
against the others.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
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
    prose."""
    lessons = postmortem.lessons
    said = (("What went well", lessons.went_well if lessons else []),
            ("What went wrong", lessons.went_wrong if lessons else []),
            ("Where it got lucky", lessons.got_lucky if lessons else []))

    return tuple(LessonList(heading=heading,
                            items=tuple(Line(runs=(Run(text=lesson, role=Role.PROSE),))
                                        for lesson in listed),
                            absent=None if listed else _NOTHING)
                 for heading, listed in said)
