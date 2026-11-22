"""How detection is said - the lesson as one sentence, and an alert sooner than
its rule's wait - which the page and the brief the model writes from both say
alike."""

from __future__ import annotations

from datetime import timedelta

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import DetectionLesson, DetectionMeasuredFrom
from narration import shorter_than_the_rules_wait, the_detection_lesson_said


@pytest.mark.parametrize(("lesson", "said"), [
    (DetectionLesson(gap=timedelta(minutes=6, seconds=2),
                     measured_from=DetectionMeasuredFrom.LINE_PASSED,
                     rule_waits=timedelta(minutes=5), rule_looks_back=timedelta(0),
                     rule_evaluated_every=timedelta(minutes=1),
                     scraping_and_storing=timedelta(seconds=30)),
     "The alert came <gap> after its series passed its line, within the <accounted_for> "
     "accounted for by its rule waiting <rule_waits> with its condition holding, its "
     "evaluation at intervals of <rule_evaluated_every>, an unmeasured allowance of "
     "<scraping_and_storing> for scraping and storing its samples and the whole minute its "
     "series is read in."),
    (DetectionLesson(gap=timedelta(minutes=20),
                     measured_from=DetectionMeasuredFrom.ONSET,
                     rule_waits=timedelta(minutes=5), rule_looks_back=timedelta(minutes=2),
                     rule_evaluated_every=timedelta(minutes=1),
                     scraping_and_storing=timedelta(seconds=30)),
     "The alert came <beyond> later than the <accounted_for> accounted for by its rule "
     "waiting <rule_waits> with its condition holding, its condition looking back over "
     "<rule_looks_back>, its evaluation at intervals of <rule_evaluated_every>, an "
     "unmeasured allowance of <scraping_and_storing> for scraping and storing its samples "
     "and the whole minute the onset is measured to. The record does not show what took the "
     "rest.")
], ids=["within-from-the-line", "later-from-the-onset"])
@pytest.mark.unit
def test_the_lesson_on_detection_says_each_span_as_whoever_shows_it_says_one(
        lesson: DetectionLesson, said: str) -> None:
    # The page and the brief the model writes from both say it, and two
    # spellings of one weighing read as two weighings - one of them a lag the
    # other counts as the rule's own time. Each span comes in as each says one:
    # the page's own way, the brief's with the figure's name.
    Scenario() \
        .when(
            lambda: the_detection_lesson_said(lesson, lambda part, _: f"<{part}>")
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.parametrize(("held", "said"), [
    (True, ", so the condition held before the measured onset"),
    (False, ", though not every minute of that wait before the measured onset met it"),
    (None, "")
], ids=["held", "did-not-hold", "unread"])
@pytest.mark.unit
def test_an_alert_sooner_than_its_rule_s_wait_is_said_with_what_the_series_bore_out(
        held: bool | None, said: str) -> None:
    # The page beside the gap and the brief the model writes from both say it,
    # and two spellings of one fact read as two facts. The wait comes in as
    # each says a span - the page's own way, the brief's with the figure's name.
    Scenario() \
        .when(
            lambda: shorter_than_the_rules_wait("5m 0s", held)
        ) \
        .then(
            the_answer_was(f"shorter than the 5m 0s its rule's condition must hold before it "
                           f"fires{said}")
        )
