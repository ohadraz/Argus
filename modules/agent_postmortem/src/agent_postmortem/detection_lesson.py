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
from typing import Final

from argus_core.models import DetectionLesson, DetectionMeasuredFrom

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements

# How long a sample can take to be scraped and stored before the rule can
# evaluate it - time Argus reads nothing of, and which an alert seconds past
# everything else the rule spends would otherwise be called slow for.
SCRAPING_AND_STORING: Final = timedelta(seconds=30)


def the_detection_lesson(evidence: IncidentEvidence,
                         measured: Measurements) -> DetectionLesson | None:
    """How soon the alert came and what the rule spends before it can - or
    `None` where that cannot be weighed.

    Not where the page's Detection section already says why: no onset, no rule
    read, an alert before its start or sooner than the rule's wait. Nor where
    the series was read with its line and never past it before the alert: it
    does not bear out when the rule could fire - often the minute it passed
    was not read yet - and weighed from the onset instead, the fault's own
    growth would be called slow detection.
    """
    if (measured.onset_at is None or measured.rule_waits is None
            or measured.rule_looks_back is None or measured.rule_evaluated_every is None):
        return None

    if measured.rule_line_read:
        if measured.rule_past_its_line_at is None:
            return None

        began = measured.rule_past_its_line_at
        measured_from = DetectionMeasuredFrom.LINE_PASSED
        looks_back = timedelta(0)
    else:
        began = measured.onset_at
        measured_from = (DetectionMeasuredFrom.METRICS_STOPPED
                         if measured.unobserved_from is not None
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
