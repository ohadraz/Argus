"""How it was found: when it began, when the alert fired, and how long that took.

Each case is one postmortem and the sentence the section says it in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import Detection
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.detection import DetectionSection, the_detection
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem, an_alert

SOME_ONSET = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)
SOME_ALERT = SOME_ONSET + timedelta(minutes=2, seconds=40)


@pytest.mark.unit
def test_detection_says_when_it_began_when_the_alert_fired_and_the_gap() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=SOME_ALERT, rule="dont care", onset_at=SOME_ONSET,
                gap=timedelta(minutes=2, seconds=40)))
        ) \
        .when(
            lambda: the_detection(some_postmortem, an_alert("HighErrorRate", "io-shop")).line
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="The incident on "),
                                      Run(text="io-shop", role=Role.CODE),
                                      Run(text=" began at "),
                                      Run.a_moment(SOME_ONSET),
                                      Run(text=". HighErrorRate fired at "),
                                      Run.a_moment(SOME_ALERT),
                                      Run(text=", 2m 40s later"),
                                      Run(text=".")))))


@pytest.mark.unit
def test_an_unknown_onset_is_said_to_be_and_no_gap_is_given() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=SOME_ALERT, rule="dont care", onset_at=None, gap=None))
        ) \
        .when(
            lambda: the_detection(some_postmortem, an_alert("HighErrorRate", "io-shop")).line
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="The onset is unknown. HighErrorRate fired at "),
                                      Run.a_moment(SOME_ALERT),
                                      Run(text=".")))))


@pytest.mark.unit
def test_detection_nobody_recorded_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=None)
        ) \
        .when(
            lambda: the_detection(some_postmortem, an_alert())
        ) \
        .then(
            the_answer_was(DetectionSection(line=None,
                                            absent="How it was detected was not recorded.")))
