"""The lesson on detection: how soon the alert came, against what its rule
spends before it can fire.

Asked to weigh it, three write-ups of one incident in a row weighed nothing,
and one counted a wait its rule did not have. Every part of the judgement is
measured, so code works it out and the page says it (`postmortem_rendering`).

The time to the alert runs from the first minute the rule's own series was
past its line, where that was read: a fault that grows reaches the line minutes
after the onset, and those minutes are the fault's, not detection's. The
series is the rule's own query, so its look-back is in every reading and is not
counted again from there. Where no line was read - an absence check has no
series at all - it runs from the onset, look-back and all.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Final

from argus_core.models import DetectionLesson, DetectionMeasuredFrom

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements

# How long a sample can take to be scraped and stored before the rule can
# evaluate it - time Argus reads nothing of, and which an alert seconds past
# everything else the rule spends would otherwise be called slow for.
SCRAPING_AND_STORING: Final = timedelta(seconds=30)


class NoStartFromTheLine(StrEnum):
    """Why the rule's series, read with its line, shows no start the alert
    can be weighed from: never past it before the alert, or first read past
    it less than the rule's wait before the alert - when the rule held before
    the first minute read past, which can lag its own evaluation."""

    NEVER_PAST = "never past"
    PAST_TOO_LATE = "past too late"


def no_start_from_the_line(evidence: IncidentEvidence,
                           measured: Measurements) -> NoStartFromTheLine | None:
    """Where the rule's series was read with its line and bears out no start
    the alert can be weighed from - `None` everywhere else.

    Counted from the onset there, what came after the rule's wait is the
    fault's own growth, said as slow detection. Not where the alert came
    sooner after the onset than the wait, or before it, which is said as that
    from either start.
    """
    if (measured.onset_at is None or measured.rule_waits is None
            or not measured.rule_line_read
            or evidence.alerted_at - measured.onset_at < measured.rule_waits):
        return None

    if measured.rule_past_its_line_at is None:
        return NoStartFromTheLine.NEVER_PAST

    if evidence.alerted_at - measured.rule_past_its_line_at < measured.rule_waits:
        return NoStartFromTheLine.PAST_TOO_LATE

    return None


def the_detection_lesson(evidence: IncidentEvidence,
                         measured: Measurements) -> DetectionLesson | None:
    """How soon the alert came and what the rule spends before it can - or
    `None` where that cannot be weighed.

    Not where the page's Detection section already says why, which it says of
    the onset: no onset, no rule read, an alert before the onset or sooner
    after it than the rule's wait. Nor where the series was read with its line
    and does not bear out when the rule could fire - never past it before the
    alert (often the minute it passed was not read yet), or past it too late
    for the alert to have waited out the rule's wait after. Weighed from the
    onset instead, the fault's own growth would be called slow detection.

    Nor where the alert's own dating of the fault is all that dates the onset:
    the check that raised it found it on its own schedule, which the alert
    says, and the rule's timing accounts for none of the time to it. An
    absence rule dates the minute the metrics stopped, and watches all the
    time: that gap is its own, and weighed.
    """
    dated_only_by_the_alert = (measured.onset_at == evidence.onset_stated_by_the_alert
                               and measured.metrics_stopped_at is None)
    if (measured.onset_at is None or dated_only_by_the_alert
            or measured.rule_waits is None
            or measured.rule_looks_back is None or measured.rule_evaluated_every is None):
        return None

    if measured.rule_line_read:
        if measured.rule_past_its_line_at is None:
            return None

        # Past it in the onset's own minute, it passed it then or earlier:
        # no crossing to say the alert came after, so the onset is the start.
        began = measured.rule_past_its_line_at
        measured_from = (DetectionMeasuredFrom.ONSET if began == measured.onset_at
                         else DetectionMeasuredFrom.LINE_PASSED)
        looks_back = timedelta(0)
    else:
        began = measured.onset_at
        measured_from = (DetectionMeasuredFrom.METRICS_STOPPED
                         if measured.metrics_stopped_at is not None
                         else DetectionMeasuredFrom.ONSET)
        looks_back = measured.rule_looks_back

    gap = evidence.alerted_at - began
    if gap < measured.rule_waits:
        return None

    return DetectionLesson(gap=gap,
                           measured_from=measured_from,
                           rule_waits=measured.rule_waits,
                           rule_looks_back=looks_back,
                           rule_evaluated_every=measured.rule_evaluated_every,
                           scraping_and_storing=SCRAPING_AND_STORING)
