"""The lesson on detection, worked out by code.

Asked to weigh how soon the alert came, three write-ups of one incident in a row
weighed nothing - one counted a wait its rule did not have. Everything the
judgement needs is measured: where the time to the alert runs from, the alert,
and what the paging rule spends before it can fire. So code works it out, and
the page says it.

From the first minute the rule's own series was past its line, where that was
read: a fault that grows reaches the line minutes after the onset, and those
minutes are the fault's, not detection's. The look-back is not counted from
there - the series is the rule's own query, so its window is in each reading.
From the onset where no line was read, look-back and all.

Where the page's Detection section already says why the gap cannot be weighed -
no onset, no rule read, an alert before its start or sooner than the wait - and
where the series was read with its line and never passed it before the alert,
there is no lesson.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from agent_postmortem.detection_lesson import SCRAPING_AND_STORING, the_detection_lesson
from argus_core.models import DetectionLesson, DetectionMeasuredFrom
from argus_testkit import Assertion, Scenario, the_answer_was

from agent_postmortem_test.framework.builders import (
    ONSET,
    a_measured_incident,
    an_evidence_bundle,
)


@pytest.mark.unit
def test_where_no_line_was_read_the_alert_is_weighed_from_the_onset_look_back_and_all() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=5, seconds=53)),
            measured := a_measured_incident(rule_waits=timedelta(minutes=1),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(seconds=30))
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            the_answer_was(DetectionLesson(gap=timedelta(minutes=5, seconds=53),
                                           measured_from=DetectionMeasuredFrom.ONSET,
                                           rule_waits=timedelta(minutes=1),
                                           rule_looks_back=timedelta(minutes=5),
                                           rule_evaluated_every=timedelta(seconds=30),
                                           scraping_and_storing=SCRAPING_AND_STORING))
        )


@pytest.mark.unit
def test_where_the_rules_series_passed_its_line_the_alert_is_weighed_from_there_without_look_back(
) -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6)),
            measured := a_measured_incident(rule_waits=timedelta(minutes=1),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(seconds=30),
                                            rule_past_its_line_at=ONSET + timedelta(minutes=2),
                                            rule_line_read=True)
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            the_answer_was(DetectionLesson(gap=timedelta(minutes=4),
                                           measured_from=DetectionMeasuredFrom.LINE_PASSED,
                                           rule_waits=timedelta(minutes=1),
                                           rule_looks_back=timedelta(0),
                                           rule_evaluated_every=timedelta(seconds=30),
                                           scraping_and_storing=SCRAPING_AND_STORING))
        )


@pytest.mark.unit
def test_a_series_already_past_its_line_at_the_onset_is_weighed_from_the_onset_without_look_back(
) -> None:
    # Past it in the onset's own minute, it passed it then or earlier - not a
    # crossing to say the alert came after. Still the rule's own readings, so
    # the look-back is in them.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6)),
            measured := a_measured_incident(rule_waits=timedelta(minutes=1),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(seconds=30),
                                            rule_past_its_line_at=ONSET,
                                            rule_line_read=True)
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            the_answer_was(DetectionLesson(gap=timedelta(minutes=6),
                                           measured_from=DetectionMeasuredFrom.ONSET,
                                           rule_waits=timedelta(minutes=1),
                                           rule_looks_back=timedelta(0),
                                           rule_evaluated_every=timedelta(seconds=30),
                                           scraping_and_storing=SCRAPING_AND_STORING))
        )


@pytest.mark.unit
def test_where_the_metrics_stopped_at_the_onset_the_alert_is_weighed_from_their_stopping() -> None:
    # The same instant, and a different thing to have dated: the page says it
    # as the metrics stopping, as Detection does.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=5, seconds=53)),
            measured := a_measured_incident(rule_waits=timedelta(0),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(minutes=1),
                                            unobserved_from=ONSET)
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            _measured_from(DetectionMeasuredFrom.METRICS_STOPPED)
        )


@pytest.mark.unit
def test_an_onset_the_alert_stated_where_the_metrics_stopped_keeps_its_lesson() -> None:
    # An absence rule dates the incident too - the minute it last heard from
    # the service - and that is the minute the metrics stopped. It watches all
    # the time, so the gap to the alert is its own, unlike a check that
    # reconciles on a schedule of its own.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_stated_by_the_alert=ONSET,
                                           alerted_at=ONSET + timedelta(minutes=5, seconds=8)),
            measured := a_measured_incident(rule_waits=timedelta(0),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(minutes=1),
                                            unobserved_from=ONSET)
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            _measured_from(DetectionMeasuredFrom.METRICS_STOPPED)
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("onset_at", "after_the_onset", "rule_waits", "unread", "line_read"), [
        (None, timedelta(minutes=5), timedelta(0), False, False),
        (ONSET, timedelta(minutes=5), None, False, False),
        (ONSET, timedelta(minutes=5), None, True, False),
        (ONSET, -timedelta(minutes=1), timedelta(0), False, False),
        (ONSET, timedelta(minutes=1), timedelta(minutes=2), False, False),
        (ONSET, timedelta(minutes=5), timedelta(0), False, True)
    ],
    ids=["no-onset", "no-rule-paged", "rule-unread", "alert-before-the-onset",
         "alert-sooner-than-the-wait", "line-read-and-never-passed"])
def test_a_gap_that_cannot_be_weighed_is_no_lesson(
        onset_at: datetime | None, after_the_onset: timedelta, rule_waits: timedelta | None,
        unread: bool, line_read: bool) -> None:
    # The first five the page's Detection section already says. The last is a
    # series that does not bear out when the rule could fire - often the
    # minute it passed was not yet read - and weighed from the onset instead it
    # would count the fault's own growth as slow detection.
    rule_read = rule_waits is not None

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=onset_at,
                                           alerted_at=ONSET + after_the_onset),
            measured := a_measured_incident(
                onset_at=onset_at,
                rule_waits=rule_waits,
                rule_wait_unread=unread,
                rule_looks_back=timedelta(minutes=5) if rule_read else None,
                rule_evaluated_every=timedelta(minutes=1) if rule_read else None,
                rule_line_read=line_read)
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_an_onset_the_alert_dated_itself_is_no_lesson() -> None:
    # A check that reconciles stored figures dates the fault by the oldest
    # record it found wrong, and finds it on its own schedule - a week later,
    # by design. The gap is that schedule, which the alert says, and the
    # rule's own timing accounts for none of it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_stated_by_the_alert=ONSET,
                                           alerted_at=ONSET + timedelta(days=7)),
            measured := a_measured_incident(rule_waits=timedelta(minutes=1),
                                            rule_looks_back=timedelta(minutes=5),
                                            rule_evaluated_every=timedelta(seconds=30))
        ) \
        .when(
            lambda: the_detection_lesson(evidence, measured)
        ) \
        .then(
            the_answer_was(None)
        )


def _measured_from(expected: DetectionMeasuredFrom) -> Assertion[DetectionLesson | None]:
    def assertion(lesson: DetectionLesson | None) -> bool:
        if lesson is None or lesson.measured_from is not expected:
            raise AssertionError(
                f"Expected a lesson measured from [{expected}], got [{lesson}].")

        return True

    return assertion
