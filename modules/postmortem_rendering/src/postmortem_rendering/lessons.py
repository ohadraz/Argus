"""What was learned, in three lists: what went well, what went wrong, and where
the incident got lucky - each present, empty or not, so a reader weighs one
against the others.

And the lesson on detection, which code writes from what was measured: said
here in words of the page's own, first in the list it belongs in - within what
the rule spends before it can fire, it went well; beyond it, wrong by the rest.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from argus_core import said_as_a_span
from argus_core.models import DetectionLesson, DetectionMeasuredFrom, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run

_NOTHING: Final = "Nothing."

_WHAT_TOOK_THE_REST: Final = "The record does not show what took the rest."

# The whole minute each start is measured to, which the time from it to the
# alert can hold without the rule having spent any of it.
_A_WHOLE_MINUTE: Final = timedelta(minutes=1)

# What the gap runs from, as the sentence says it after "The alert came 5
# minutes" - only where it runs from its series passing its line, since the
# Detection section says the gap from any other start - and the whole minute
# each start is measured to, as its last part.
_AFTER_ITS_LINE: Final = "after its series passed its line"
_THE_WHOLE_MINUTE: Final = {
    DetectionMeasuredFrom.ONSET: "the whole minute the onset is measured to",
    DetectionMeasuredFrom.METRICS_STOPPED: "the whole minute the metrics' stopping is measured to",
    DetectionMeasuredFrom.LINE_PASSED: "the whole minute its series is read in"
}


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
    said = (("What went well",
             (_said(detection),) if detection and _went_well(detection) else (),
             lessons.went_well if lessons else []),
            ("What went wrong",
             (_said(detection),) if detection and not _went_well(detection) else (),
             lessons.went_wrong if lessons else []),
            ("Where it got lucky", (), lessons.got_lucky if lessons else []))

    return tuple(LessonList(heading=heading,
                            items=(*written,
                                   *(Line(runs=(Run(text=lesson, role=Role.PROSE),))
                                     for lesson in listed)),
                            absent=None if written or listed else _NOTHING)
                 for heading, written, listed in said)


def _accounted_for(lesson: DetectionLesson) -> timedelta:
    """Everything the rule and the reading spend before the alert can come."""
    return (lesson.rule_waits + lesson.rule_looks_back + lesson.rule_evaluated_every
            + lesson.scraping_and_storing + _A_WHOLE_MINUTE)


def _went_well(lesson: DetectionLesson) -> bool:
    """Whether the alert came within what was accounted for, to the second."""
    return lesson.gap <= _accounted_for(lesson)


def _said(lesson: DetectionLesson) -> Line:
    """The lesson as one sentence: how long after its start the alert came,
    how that stands against what was accounted for, and each part of that -
    a part of nothing left out, since it spends no time.

    How long only where it runs from where the Detection section's does not:
    from the onset, or the metrics stopping it dates, Detection says it, and
    said here as well, a page told it twice."""
    parts = [
        *((f"its rule waiting {said_as_a_span(lesson.rule_waits)} with its condition "
           f"holding",) if lesson.rule_waits else ()),
        *((f"its condition looking back over {said_as_a_span(lesson.rule_looks_back)}",)
          if lesson.rule_looks_back else ()),
        *((f"its evaluation at intervals of {said_as_a_span(lesson.rule_evaluated_every)}",)
          if lesson.rule_evaluated_every else ()),
        # An allowance nobody measured, said as one: in the voice of the
        # rule's own parts it would read as a fact about the stack.
        *((f"an unmeasured allowance of {said_as_a_span(lesson.scraping_and_storing)} for "
           f"scraping and storing its samples",) if lesson.scraping_and_storing else ()),
        _THE_WHOLE_MINUTE[lesson.measured_from]
    ]
    by = ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else parts[0]
    accounted_for = _accounted_for(lesson)
    went_well = _went_well(lesson)
    gap_said = lesson.measured_from is DetectionMeasuredFrom.LINE_PASSED
    against = (f"within the {said_as_a_span(accounted_for)}" if went_well
               else f"{said_as_a_span(lesson.gap - accounted_for)} "
                    f"{'more' if gap_said else 'later'} than the "
                    f"{said_as_a_span(accounted_for)}")
    # A rule can spend time the rule Argus reads does not say - an absence
    # check's own dwell - so the rest is said to be unknown rather than left
    # to read as detection's fault.
    unknown = "" if went_well else f" {_WHAT_TOOK_THE_REST}"
    came = f"{said_as_a_span(lesson.gap)} {_AFTER_ITS_LINE}, " if gap_said else ""

    return Line(runs=(Run(text=f"The alert came {came}{against} accounted for "
                               f"by {by}.{unknown}"),))
