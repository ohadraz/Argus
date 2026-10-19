"""What was done to end it: a person's resolution where there is one, every
action taken, and the fix proposed beside them - the mitigation ended the
symptom, the fix is what ends the cause.

Each case is one postmortem and what the section says.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import OpenedPullRequest, ResolutionStep, TimelineEntry
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.actions_taken import StepRow, the_actions_taken, the_person_who_resolved
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
                               by="Argus", reversible=True,
                               outcome="recovered, still in place", label="M1")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None).steps
        ) \
        .then(
            the_answer_was((StepRow(label="M1", at="14:08:30",
                                    action=Line(runs=(Run(
                                        text="turned monthly-spend-feature off"),)),
                                    by="Argus", kind="reversible",
                                    outcome="recovered, still in place"),)))


@pytest.mark.unit
def test_an_action_that_left_automatic_sync_off_says_so_in_its_row_alone() -> None:
    # In the table, beside whether the action still stands, which is what the
    # sync being off explains - and not in the outcome a citation of the action
    # shows, which is about what it came to and is cited wherever it is.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="rolled back io-shop", by="Argus",
                               reversible=True, outcome="confirmed, still in place",
                               label="M1", sync_left_off=True)])
        ) \
        .when(
            lambda: [(step.outcome, step.outcome_in_the_table) for step in
                     the_actions_taken(some_postmortem, resolution=None).steps]
        ) \
        .then(
            the_answer_was([("confirmed, still in place",
                             "confirmed, still in place - automatic sync left off")]))


@pytest.mark.unit
def test_an_action_that_cannot_be_undone_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=SOME_MOMENT, action="dont care", by="dont care",
                               reversible=False, outcome="dont care", label="M1")])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None).steps[0].kind
        ) \
        .then(
            the_answer_was("irreversible"))


@pytest.mark.unit
def test_the_table_names_its_columns_and_their_zone() -> None:
    Scenario() \
        .given(
            dont_care_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_actions_taken(dont_care_postmortem, resolution=None).headings
        ) \
        .then(
            the_answer_was(("Time (UTC)", "Action", "By", "Kind", "Outcome")))


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
            lambda: the_actions_taken(some_postmortem, resolution=None).fix
        ) \
        .then(
            the_answer_was(StepRow(label=None, at="14:08:30",
                                   action=Line(runs=(Run(text="proposed a fix: "),
                                                     Run(text="PR #7", role=Role.LINK,
                                                         address=SOME_FIX.url))),
                                   by="Code-Fix Agent", kind="needs a person to merge",
                                   outcome="draft - not merged")))


@pytest.mark.unit
def test_a_fix_no_line_dates_has_no_time() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(pull_request=SOME_FIX, timeline=[])
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None).fix
        ) \
        .then(
            _it_is_dated("-"))


@pytest.mark.unit
def test_a_person_s_resolution_is_said_before_the_actions() -> None:
    some_resolution = ReportedResolution(by="Kuki Buki", channel="the Argus UI",
                                         at=SOME_MOMENT, note="rolled the flag back by hand")

    Scenario() \
        .given(
            some_resolution
        ) \
        .when(
            lambda: the_actions_taken(a_postmortem(), resolution=some_resolution).person
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
            the_answer_was(the_actions_taken(a_postmortem(), resolution=some_resolution).person))


@pytest.mark.unit
def test_nothing_done_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[], pull_request=None)
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=None).absent
        ) \
        .then(
            the_answer_was("Nothing was done to end it."))


@pytest.mark.unit
def test_an_incident_only_a_person_ended_is_not_one_where_nothing_was_done() -> None:
    some_resolution = ReportedResolution(by="dont care", channel="dont care",
                                         at=SOME_MOMENT, note=None)

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[], pull_request=None)
        ) \
        .when(
            lambda: the_actions_taken(some_postmortem, resolution=some_resolution).absent
        ) \
        .then(
            the_answer_was(None))


def _it_is_dated(expected: str) -> Assertion[StepRow | None]:
    def assertion(row: StepRow | None) -> bool:
        dated = row.at if row is not None else None

        if dated != expected:
            raise AssertionError(f"Expected the row dated [{expected}], got [{dated}].")

        return True

    return assertion
