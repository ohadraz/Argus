"""How it was found: when it began, when the alert fired, and how long that took.

Each case is one postmortem and the sentence the section says it in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import CitedEvidence, Detection
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.detection import DetectionSection, the_detection
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import EvidenceRow

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
def test_an_alert_dated_before_the_measured_onset_is_said_to_be() -> None:
    # The sender dates the alert and Argus measures the onset, and the two can
    # cross - a rule with no wait fires on the first minute that departs, a
    # sender's clock runs ahead. "-1m 20s later" is a sentence nobody can read.
    some_earlier_alert = SOME_ONSET - timedelta(minutes=1, seconds=20)

    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=some_earlier_alert, rule="dont care", onset_at=SOME_ONSET,
                gap=some_earlier_alert - SOME_ONSET))
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
                                      Run.a_moment(some_earlier_alert),
                                      Run(text=", 1m 20s before the measured onset"),
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
def test_what_the_alert_said_is_a_row_under_the_label_it_is_cited_by() -> None:
    # A chain's symptom rests on it, and a citation of it leads here.
    some_finding = "240 of 240 shopper totals do not reconcile"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=SOME_ALERT, rule="dont care", onset_at=None, gap=None,
                said=CitedEvidence(label="AL1", text=some_finding)))
        ) \
        .when(
            lambda: the_detection(some_postmortem, an_alert()).said
        ) \
        .then(
            the_answer_was(EvidenceRow(label="AL1", said=Line(runs=(Run(text=some_finding),)))))


@pytest.mark.unit
def test_an_alert_that_said_nothing_of_its_own_has_no_row() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=SOME_ALERT, rule="dont care", onset_at=None, gap=None, said=None))
        ) \
        .when(
            lambda: the_detection(some_postmortem, an_alert()).said
        ) \
        .then(
            the_answer_was(None))


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
