"""What a postmortem says before any section: its title, and the rows a reader
asks about before reading any of it.

Which incident, when it was broken, how finished the document is, who wrote it
and when, and who ended the incident. Each case is one postmortem and the words
one of these comes out as - read as said, since the words are what the page and
the PDF must agree on, and the parts each plays only how each shows them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChangeKind,
    ResolutionStep,
    ReviewCriterion,
    TimelineMarker,
    Trigger,
)
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.head import a_head, a_title
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import ReportedResolution

from postmortem_rendering_test.framework.builders import a_marker, a_postmortem, an_alert

SOME_ONSET = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)


@pytest.mark.unit
def test_a_title_is_the_symptom_and_the_flag_change_it_began_with() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                symptom="Account pages failed",
                trigger=Trigger(subject="monthly-spend-feature", from_state="off", to_state="on",
                                changed_at=None, kind=ChangeKind.FLAG_TOGGLE))
        ) \
        .when(
            lambda: a_title(some_postmortem, an_alert())
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Account pages failed"),
                                      Run(text=" while "),
                                      Run(text="monthly-spend-feature", role=Role.CODE),
                                      Run(text=" was "),
                                      Run(text="on")))))


@pytest.mark.unit
def test_a_title_names_a_deployment_as_the_service_running_the_revision() -> None:
    # A deployment's subject is the service and its state a revision, so the
    # title says what was running rather than what something "was".
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                symptom="Checkout failed",
                trigger=Trigger(subject="dont care", from_state=None,
                                to_state="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
                                changed_at=None, kind=ChangeKind.DEPLOY))
        ) \
        .when(
            lambda: a_title(some_postmortem, an_alert(service="io-shop"))
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Checkout failed"),
                                      Run(text=" while "),
                                      Run(text="io-shop", role=Role.CODE),
                                      Run(text=" ran "),
                                      Run(text="26f1d7e", role=Role.CODE)))))


@pytest.mark.unit
def test_a_suspected_trigger_stays_out_of_the_title() -> None:
    # The title is read by everybody who reads nothing else, and there a
    # change nothing tested would read as the change that did it.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                symptom="Account pages failed",
                trigger=Trigger(subject="monthly-spend-feature", from_state="off", to_state="on",
                                changed_at=None, suspected=True))
        ) \
        .when(
            lambda: a_title(some_postmortem, an_alert()).said
        ) \
        .then(
            the_answer_was("Account pages failed"))


@pytest.mark.unit
def test_a_postmortem_naming_no_symptom_is_titled_by_its_alert() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(symptom=None)
        ) \
        .when(
            lambda: a_title(some_postmortem, an_alert("HighErrorRate", "io-shop")).said
        ) \
        .then(
            the_answer_was("HighErrorRate on io-shop"))


@pytest.mark.unit
def test_an_incident_with_no_postmortem_is_titled_by_its_alert() -> None:
    Scenario() \
        .given(
            no_postmortem := None
        ) \
        .when(
            lambda: a_title(no_postmortem, an_alert("HighErrorRate", "io-shop")).said
        ) \
        .then(
            the_answer_was("HighErrorRate on io-shop"))


@pytest.mark.unit
def test_the_head_s_rows_are_labelled_in_the_order_a_reader_asks() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: a_head(dont_care_postmortem, an_alert(), resolution=None).labels
        ) \
        .then(
            the_answer_was(("Incident", "Date", "Status", "Written by", "Ended by")))


@pytest.mark.unit
def test_the_head_names_the_incident_by_its_alert_and_service() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: a_head(dont_care_postmortem, an_alert("HighErrorRate", "io-shop"),
                           resolution=None).incident
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="HighErrorRate", role=Role.CODE),
                                      Run(text=" on "),
                                      Run(text="io-shop", role=Role.CODE)))))


@pytest.mark.unit
def test_the_head_dates_the_incident_from_onset_to_recovery_saying_the_day_once() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                a_marker(TimelineMarker.IMPACT_BEGINS, SOME_ONSET),
                a_marker(TimelineMarker.IMPACT_ENDS, SOME_ONSET + timedelta(minutes=9))])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).date
        ) \
        .then(
            _it_reads("Oct 11, 2026, 14:03 to 14:12 UTC"))


@pytest.mark.unit
def test_the_head_carries_both_ends_of_the_incident_for_a_reader_s_own_clock() -> None:
    # The page says the window again on the reader's clock; the words are UTC,
    # and the two instants ride along with them.
    some_recovery = SOME_ONSET + timedelta(minutes=9)

    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                a_marker(TimelineMarker.IMPACT_BEGINS, SOME_ONSET),
                a_marker(TimelineMarker.IMPACT_ENDS, some_recovery)])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).date
        ) \
        .then(
            _it_carries_the_moments(SOME_ONSET, some_recovery))


@pytest.mark.unit
def test_an_incident_ending_on_another_day_says_both_days() -> None:
    some_late_onset = datetime(2026, 10, 11, 23, 58, tzinfo=UTC)

    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                a_marker(TimelineMarker.IMPACT_BEGINS, some_late_onset),
                a_marker(TimelineMarker.IMPACT_ENDS, some_late_onset + timedelta(minutes=6))])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).date
        ) \
        .then(
            _it_reads("Oct 11, 2026, 23:58 to Oct 12, 2026, 00:04 UTC"))


@pytest.mark.unit
def test_an_incident_with_no_recovery_seen_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[
                a_marker(TimelineMarker.IMPACT_BEGINS, SOME_ONSET)])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).date
        ) \
        .then(
            _it_reads("Oct 11, 2026, 14:03 UTC, no recovery seen"))


@pytest.mark.unit
def test_an_incident_with_no_onset_says_it_is_unknown() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(timeline=[])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).date
        ) \
        .then(
            _it_reads("onset unknown"))


@pytest.mark.unit
def test_a_document_nobody_has_reviewed_is_a_draft_and_counts_its_items_done() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                review=[ReviewCriterion(criterion="dont care", met=True),
                        ReviewCriterion(criterion="dont care", met=None)],
                action_items=[_an_action_item("AI-1", ActionItemStatus.DONE),
                              _an_action_item("AI-2", ActionItemStatus.OPEN)])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).status
        ) \
        .then(
            _it_reads("Draft. 1 of 2 action items are done."))


@pytest.mark.unit
def test_a_document_with_nothing_left_for_a_person_is_final() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                review=[ReviewCriterion(criterion="dont care", met=True)],
                action_items=[])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).status
        ) \
        .then(
            _it_reads("Final. No action items."))


@pytest.mark.unit
def test_the_head_says_who_wrote_the_document_when_and_whether_anybody_reviewed_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                created_at=datetime(2026, 10, 11, 14, 30, tzinfo=UTC),
                review=[ReviewCriterion(criterion="dont care", met=None)])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).written_by
        ) \
        .then(
            _it_reads("Argus Postmortem agent, Oct 11, 2026, 14:30 UTC. Not reviewed yet."))


@pytest.mark.unit
def test_an_incident_a_person_resolved_was_ended_by_them() -> None:
    Scenario() \
        .given(
            some_resolution := ReportedResolution(by="Kuki Buki",
                                                  channel="the Argus UI",
                                                  at=datetime(2026, 10, 11, 14, 20, tzinfo=UTC),
                                                  note="rolled the flag back by hand")
        ) \
        .when(
            lambda: a_head(a_postmortem(), an_alert(), resolution=some_resolution).ended_by
        ) \
        .then(
            _it_reads("Kuki Buki from the Argus UI, Oct 11, 2026, 14:20 UTC"
                      " - rolled the flag back by hand"))


@pytest.mark.unit
def test_an_incident_argus_ended_was_ended_by_its_last_step() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_ONSET, action="Turned monthly-spend-feature off",
                               by="Argus", reversible=True,
                               outcome="recovered, still in place", label="M1")])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).ended_by
        ) \
        .then(
            _it_reads("Argus: turned monthly-spend-feature off - recovered, still in place"))


@pytest.mark.unit
def test_whoever_ended_the_incident_is_named_on_its_own() -> None:
    # For a destination that marks who it was: the page tags the row with them.
    Scenario() \
        .given(
            some_resolution := ReportedResolution(by="Kuki Buki", channel="dont care",
                                                  at=SOME_ONSET, note=None)
        ) \
        .when(
            lambda: a_head(a_postmortem(), an_alert(), resolution=some_resolution).ended_by_whom
        ) \
        .then(
            the_answer_was("Kuki Buki"))


@pytest.mark.unit
def test_an_incident_nobody_is_recorded_ending_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[])
        ) \
        .when(
            lambda: a_head(some_postmortem, an_alert(), resolution=None).ended_by
        ) \
        .then(
            _it_reads("Not recorded."))


def _an_action_item(number: str, status: ActionItemStatus) -> ActionItem:
    return ActionItem(number=number, text="dont care", type=ActionItemType.MITIGATE,
                      owner=None, tracking=None, status=status)


def _it_reads(expected: str) -> Assertion[Line]:
    def assertion(line: Line) -> bool:
        if line.said != expected:
            raise AssertionError(f"Expected the line to read [{expected}], got [{line.said}].")

        return True

    return assertion


def _it_carries_the_moments(*expected: datetime) -> Assertion[Line]:
    def assertion(line: Line) -> bool:
        carried = tuple(moment for run in line.runs for moment in (run.at, run.until)
                        if moment is not None)

        if carried != expected:
            raise AssertionError(f"Expected the line to carry the moments {expected}, "
                                 f"got {carried}.")

        return True

    return assertion
