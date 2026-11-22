"""How detection is said - the lesson as one sentence, and an alert sooner than
its rule's wait - the same wherever it is shown."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Final

from core.models import (
    DetectionLesson,
    DetectionMeasuredFrom,
    DetectionPart,
    accounted_for,
    within_what_was_accounted_for,
)

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

_WHAT_TOOK_THE_REST: Final = "The record does not show what took the rest."


def the_detection_lesson_said(lesson: DetectionLesson,
                              span: Callable[[DetectionPart, timedelta], str]) -> str:
    """The lesson as one sentence: how long after its start the alert came,
    how that stands against what was accounted for, and each part of that -
    a part of nothing left out, since it spends no time. Each span said by
    `span`, with the part it is.

    How long only where it runs from where the Detection section's does not:
    from the onset, or the metrics stopping it dates, Detection says it, and
    said here as well, a page told it twice.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one weighing read as
    two - one of them a lag the other counts as the rule's own time.
    """
    parts = [
        *((f"its rule waiting {span(DetectionPart.RULE_WAITS, lesson.rule_waits)} with its "
           f"condition holding",) if lesson.rule_waits else ()),
        *((f"its condition looking back over "
           f"{span(DetectionPart.RULE_LOOKS_BACK, lesson.rule_looks_back)}",)
          if lesson.rule_looks_back else ()),
        *((f"its evaluation at intervals of "
           f"{span(DetectionPart.RULE_EVALUATED_EVERY, lesson.rule_evaluated_every)}",)
          if lesson.rule_evaluated_every else ()),
        # An allowance nobody measured, said as one: in the voice of the
        # rule's own parts it would read as a fact about the stack.
        *((f"an unmeasured allowance of "
           f"{span(DetectionPart.SCRAPING_AND_STORING, lesson.scraping_and_storing)} for "
           f"scraping and storing its samples",) if lesson.scraping_and_storing else ()),
        _THE_WHOLE_MINUTE[lesson.measured_from]
    ]
    by = ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else parts[0]
    total = span(DetectionPart.ACCOUNTED_FOR, accounted_for(lesson))
    went_well = within_what_was_accounted_for(lesson)
    gap_said = lesson.measured_from is DetectionMeasuredFrom.LINE_PASSED
    against = (f"within the {total}" if went_well
               else f"{span(DetectionPart.BEYOND, lesson.gap - accounted_for(lesson))} "
                    f"{'more' if gap_said else 'later'} than the {total}")
    # A rule can spend time the rule Argus reads does not say - an absence
    # check's own dwell - so the rest is said to be unknown rather than left
    # to read as detection's fault.
    unknown = "" if went_well else f" {_WHAT_TOOK_THE_REST}"
    came = f"{span(DetectionPart.GAP, lesson.gap)} {_AFTER_ITS_LINE}, " if gap_said else ""

    return f"The alert came {came}{against} accounted for by {by}.{unknown}"


def shorter_than_the_rules_wait(waits_said: str, held_before_the_onset: bool | None) -> str:
    """An alert that came sooner after the onset than its rule's condition
    must hold, said with what the series bore out - in the words every place
    showing it uses.

    `waits_said` is the wait as the place showing it says a span, which is the
    one thing they do not share: the page writes its own, the brief the figure
    with its name. `held_before_the_onset` is whether the rule's series was
    past its line in every minute the wait reaches back to before the onset -
    `None` where that was not read, which says nothing of it.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one fact read as two
    facts.
    """
    shorter = f"shorter than the {waits_said} its rule's condition must hold before it fires"

    if held_before_the_onset is True:
        return f"{shorter}, so the condition held before the measured onset"

    if held_before_the_onset is False:
        return (f"{shorter}, though not every minute of that wait before the measured "
                f"onset met it")

    return shorter
