"""What was done to end it: a person's resolution where there is one, every
action taken, and the fix proposed beside them - the mitigation ended the
symptom, the fix is what ends the cause.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from argus_core.models import OpenedPullRequest, Refusal, ResolutionStep, TimelineEntry
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.actions_taken import (
    ActionsTakenSection,
    StepRow,
    the_actions_taken,
    the_person_who_resolved,
)
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import ReportedResolution

from postmortem_rendering_test.framework.builders import a_postmortem

SOME_MOMENT = datetime(2026, 10, 11, 14, 8, 30, tzinfo=UTC)
SOME_FIX = OpenedPullRequest(number=7, url="https://github.com/acme/shop/pull/7",
                             branch="argus/fix")


@pytest.mark.unit
def test_each_action_is_a_row_saying_when_what_who_whether_it_undoes_and_what_it_came_to() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="turned monthly-spend-feature off",
                               by="Argus", has_a_way_back=True,
                               outcome="recovered, still in place", label="M1")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).steps
        ) \
        .then(
            the_answer_was((StepRow(label="M1", at="14:08:30",
                                    action=Line(runs=(Run(
                                        text="turned monthly-spend-feature off"),)),
                                    by="Argus", kind="can be put back",
                                    outcome="recovered, still in place"),)))


@pytest.mark.unit
def test_an_action_says_the_candidate_it_was_for_citing_that_candidate_s_row() -> None:
    # Nothing else in the document says which cause an action answered, and a
    # reader left to guess takes it for the leading candidate's. Cited, so the
    # label leads to the candidate's row as it does from the prose.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="Did not roll back io-shop",
                               by="Argus", has_a_way_back=False,
                               outcome="escalated, nothing was changed", label="M1",
                               candidate="C3")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).steps[0].action
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Did not roll back io-shop for "),
                                      Run(text="C3", role=Role.CITATION, address="C3")))))


@pytest.mark.unit
def test_a_refusal_cites_the_candidate_its_words_name() -> None:
    # Its words name the candidate already, as its line in the timeline does,
    # so it is cited where it stands - leading to the candidate's row as the
    # row above it does - rather than said a second time after them.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="Refused to act on C3 - some reason",
                               by="Argus", has_a_way_back=False, outcome="not taken",
                               label=None, refused=Refusal.WOULD_UNDO_A_MEANT_CHANGE,
                               candidate="C3")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).steps[0].action
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Refused to act on "),
                                      Run(text="C3", role=Role.CITATION, address="C3"),
                                      Run(text=" - some reason")))))


@pytest.mark.unit
def test_an_action_taken_on_the_minute_says_its_time_to_the_minute() -> None:
    # As every instant is said: "14:08:00" claims a precision nothing measured.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT.replace(second=0), action="dont care",
                               by="Argus", has_a_way_back=True, outcome="dont care",
                               label="M1")])
        ) \
        .when(
            lambda: [step.at for step in the_actions_taken(some_postmortem,
                                                          resolution=None, day=None).steps]
        ) \
        .then(
            the_answer_was(["14:08"]))


@pytest.mark.unit
def test_an_action_that_left_automatic_sync_off_says_so_in_its_row_alone() -> None:
    # In the table, beside whether the action still stands, which is what the
    # sync being off explains - and not in the outcome a citation of the action
    # shows, which is about what it came to and is cited wherever it is.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="rolled back io-shop", by="Argus",
                               has_a_way_back=True, outcome="confirmed, still in place",
                               label="M1", sync_left_off=True)])
        ) \
        .when(
            lambda: [(step.outcome, step.outcome_in_the_table) for step in
                     the_actions_taken(some_postmortem, resolution=None, day=None).steps]
        ) \
        .then(
            the_answer_was([("confirmed, still in place",
                             "confirmed, still in place - automatic sync left off")]))


@pytest.mark.unit
def test_an_action_with_nothing_to_put_back_says_so() -> None:
    # Said as what the record holds, not as "irreversible": that word names the
    # autonomy tier, and a restart Argus may take unasked is on its safe side.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="dont care", by="dont care",
                               has_a_way_back=False, outcome="dont care", label="M1")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).steps[0].kind
        ) \
        .then(
            the_answer_was("nothing to put back"))


@pytest.mark.unit
def test_an_action_nobody_can_account_for_is_not_said_to_leave_nothing_to_put_back() -> None:
    # An outcome saying nobody knows whether anything was changed, beside a
    # Kind saying there is nothing to put back, contradicts itself.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="dont care", by="dont care",
                               has_a_way_back=False, left_behind_known=False,
                               outcome="escalated, not known whether anything was changed",
                               label="M1")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).steps[0].kind
        ) \
        .then(
            the_answer_was("not known whether anything is left to put back"))


@pytest.mark.unit
def test_the_table_names_its_columns_and_their_zone() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_actions_taken(dont_care_postmortem, resolution=None, day=None).headings
        ) \
        .then(
            the_answer_was(("", "Time (UTC)", "Action", "By", "Kind", "Outcome")))


@pytest.mark.unit
def test_the_proposed_fix_is_a_row_of_its_own_dated_by_the_line_that_proposed_it() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                pull_request=SOME_FIX,
                timeline=[TimelineEntry(at=SOME_MOMENT, who="Code-Fix Agent",
                                        text="proposed a fix")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).fix
        ) \
        .then(
            the_answer_was(StepRow(label=None, at="14:08:30",
                                   action=Line(runs=(Run(text="Proposed a fix: "),
                                                     Run(text="PR #7", role=Role.LINK,
                                                         address=SOME_FIX.url))),
                                   by="Code-Fix Agent", kind="nothing to put back",
                                   outcome="opened as a draft")))


@pytest.mark.unit
def test_a_fix_no_line_dates_has_no_time() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=SOME_FIX, timeline=[])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).fix
        ) \
        .then(
            _it_is_dated("-"))


@pytest.mark.unit
@pytest.mark.parametrize(("day", "said"), [
    (SOME_MOMENT.date(), ["14:08:30", "14:08:30"]),
    (SOME_MOMENT.date() - timedelta(days=7), ["Oct 11 14:08:30", "Oct 11 14:08:30"])
], ids=["on-the-head-s-day", "a-week-after-the-head-s-day"])
def test_an_action_and_the_fix_say_their_day_where_it_is_not_the_head_s(
        day: date, said: list[str]) -> None:
    # The head dates the incident once, and a time alone below it reads as a
    # time of that day - which a response running on a later day is not.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                resolution=[ResolutionStep(at=SOME_MOMENT, action="dont care", by="dont care",
                                           has_a_way_back=True, outcome="dont care",
                                           label="M1")],
                pull_request=SOME_FIX,
                timeline=[TimelineEntry(at=SOME_MOMENT, who="Code-Fix Agent",
                                        text="proposed a fix")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=day)
        ) \
        .then(
            _the_times_said_are(said))


@pytest.mark.unit
def test_a_person_s_resolution_is_said_before_the_actions() -> None:
    some_resolution = ReportedResolution(by="Kuki Buki", channel="the Argus UI",
                                         at=SOME_MOMENT, note="rolled the flag back by hand")

    Scenario() \
        .given(
            some_resolution
        ) \
        .when(
            lambda: the_actions_taken(a_postmortem(), resolution=some_resolution, day=None).person
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Resolved by "),
                                      Run(text="Kuki Buki", role=Role.STRONG),
                                      Run(text=" from the Argus UI, "),
                                      Run.a_moment(SOME_MOMENT),
                                      Run(text=" - "),
                                      Run(text="rolled the flag back by hand",
                                          role=Role.QUOTE)))))


@pytest.mark.unit
def test_a_person_s_resolution_is_said_the_same_where_there_is_no_document() -> None:
    # An incident a person resolved before anything was written still names
    # them, in the words the document would.
    some_resolution = ReportedResolution(by="Kuki Buki", channel="the Argus UI",
                                         at=SOME_MOMENT, note=None)

    Scenario() \
        .given(
            some_resolution
        ) \
        .when(
            lambda: the_person_who_resolved(some_resolution)
        ) \
        .then(
            the_answer_was(the_actions_taken(a_postmortem(), resolution=some_resolution,
                                             day=None).person))


@pytest.mark.unit
def test_nothing_done_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[], pull_request=None)
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).absent
        ) \
        .then(
            the_answer_was("Nothing was done to end it."))


@pytest.mark.unit
def test_a_disproven_alarm_says_nothing_needed_doing() -> None:
    # "Nothing was done to end it" reads as an incident left running.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[], pull_request=None,
                                            disproven_at=SOME_MOMENT)
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None, day=None).absent
        ) \
        .then(
            the_answer_was("Nothing needed doing: the alarm was disproven."))


@pytest.mark.unit
def test_an_incident_only_a_person_ended_is_not_one_where_nothing_was_done() -> None:
    some_resolution = ReportedResolution(by="dont care", channel="dont care",
                                         at=SOME_MOMENT, note=None)

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[], pull_request=None)
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=some_resolution, day=None).absent
        ) \
        .then(
            the_answer_was(None))


def _the_times_said_are(expected: list[str]) -> Assertion[ActionsTakenSection]:
    def assertion(taken: ActionsTakenSection) -> bool:
        said = [step.at for step in taken.steps] + ([taken.fix.at] if taken.fix else [])

        if said != expected:
            raise AssertionError(f"Expected the times {expected}, got {said}.")

        return True

    return assertion


def _it_is_dated(expected: str) -> Assertion[StepRow | None]:
    def assertion(row: StepRow | None) -> bool:
        dated = row.at if row is not None else None

        if dated != expected:
            raise AssertionError(f"Expected the row dated [{expected}], got [{dated}].")

        return True

    return assertion
