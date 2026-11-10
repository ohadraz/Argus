"""What was done to end it, as the executive synopsis lists it: a person's
resolution, one line per action, then the draft fix, then what Argus recommends
and did not do - each said with who did it, in the words the postmortem's own
page says it in, so the synopsis and the page it links to never say one action
two ways.

Each case is one postmortem, and a person's resolution or none, and the list
they give.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import NOT_JUDGED, OpenedPullRequest, Refusal, ResolutionStep
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.resolution import ReportedResolution
from postmortem_rendering.resolution_list import the_resolution_list

from postmortem_rendering_test.framework.builders import a_postmortem

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 8, 30, tzinfo=UTC)
SOME_FIX_NUMBER = 7
SOME_FIX = OpenedPullRequest(number=SOME_FIX_NUMBER,
                             url=f"https://github.com/acme/shop/pull/{SOME_FIX_NUMBER}",
                             branch="argus/fix")


@pytest.mark.unit
def test_each_action_is_said_with_who_took_it_and_what_it_came_to() -> None:
    # Without who took it, a model handed the list credits the people it was
    # told responded with Argus's revert.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Turned monthly-spend-feature off",
                               by="Argus", has_a_way_back=True,
                               outcome="recovered", label="M1")])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: turned monthly-spend-feature off - recovered",))
        )


@pytest.mark.unit
def test_an_action_is_said_without_the_label_of_the_candidate_it_was_for() -> None:
    # The label is the postmortem's own name for a candidate: a synopsis
    # reader has no row to look it up in.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Turned monthly-spend-feature off",
                               by="Argus", has_a_way_back=True,
                               outcome="recovered", label="M1", candidate="C1")])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: turned monthly-spend-feature off - recovered",))
        )


@pytest.mark.unit
def test_a_refusal_names_the_candidate_it_refused_as_a_suspected_cause() -> None:
    # A refusal's words name the label inline, where it cannot be left out
    # without leaving the sentence short.
    some_candidate = "C2"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT,
                               action=f"Refused to act on {some_candidate} - nothing named "
                                      f"what to act on",
                               by="Argus", has_a_way_back=False, outcome="not taken",
                               came_to="not taken", label=None,
                               refused=Refusal.NO_MITIGATION_PROPOSED,
                               candidate=some_candidate)])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: refused to act on a suspected cause - nothing named what to "
                            "act on - not taken",))
        )


@pytest.mark.unit
def test_a_refusal_that_recommends_is_one_line_naming_what_it_recommends() -> None:
    # Said as two lines - the refusal and then the recommendation - an
    # overview said one decision as two.
    some_candidate = "C3"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                resolution=[ResolutionStep(at=DONT_CARE_MOMENT,
                                           action=f"Refused to act on {some_candidate} - "
                                                  f"nothing would say whether it worked, so "
                                                  f"it is recommended rather than taken",
                                           by="Argus", has_a_way_back=False,
                                           outcome="not taken", came_to="not taken", label=None,
                                           refused=Refusal.NO_MITIGATION_PROPOSED,
                                           candidate=some_candidate)],
                recommended_action="Roll io-shop back")
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: refused to act on a suspected cause - nothing would say "
                            "whether it worked, so it is recommended rather than taken - "
                            "recommends: roll io-shop back",))
        )


@pytest.mark.unit
def test_an_action_a_person_s_resolution_stopped_says_who_did_not_judge_it_and_why() -> None:
    # "Not judged" alone has no subject: an overview said "no one has yet
    # judged whether it was right", where Argus never judged it because the
    # person had already ended the incident.
    some_resolution = ReportedResolution(by="Dana Kuki", channel="PagerDuty",
                                         at=DONT_CARE_MOMENT, note=None)
    some_standing = "still in place"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Reverted the feature flag kuki",
                               by="Argus", has_a_way_back=True,
                               outcome=f"{NOT_JUDGED}, {some_standing}", came_to=NOT_JUDGED,
                               standing=some_standing, label="M1")])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, some_resolution)
        ) \
        .then(
            the_answer_was((f"{some_resolution.by}: resolved it from {some_resolution.channel}",
                            f"Argus: reverted the feature flag kuki - not judged by Argus "
                            f"({some_resolution.by} resolved it first), {some_standing}"))
        )


@pytest.mark.unit
def test_an_action_stopped_with_no_person_s_resolution_is_not_judged_by_argus() -> None:
    some_standing = "still in place"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Reverted the feature flag kuki",
                               by="Argus", has_a_way_back=True,
                               outcome=f"{NOT_JUDGED}, {some_standing}", came_to=NOT_JUDGED,
                               standing=some_standing, label="M1")])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was((f"Argus: reverted the feature flag kuki - not judged by Argus, "
                            f"{some_standing}",))
        )


@pytest.mark.unit
def test_an_action_that_left_automatic_sync_off_says_so() -> None:
    # The one thing about the action that is still standing, and the page's
    # table says it beside the outcome.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Rolled io-shop back",
                               by="Argus", has_a_way_back=True,
                               outcome="recovered", label="M1", sync_left_off=True)])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: rolled io-shop back - recovered - automatic sync left off",))
        )


@pytest.mark.unit
def test_a_person_s_resolution_comes_first_and_names_them() -> None:
    # As the page shows it: who ended the incident, from where, and in their
    # words - before what Argus did on the way.
    some_resolution = ReportedResolution(by="Dana Kuki", channel="Slack", at=DONT_CARE_MOMENT,
                                         note="turned the flag off myself")

    Scenario() \
        .given(
            some_postmortem := a_postmortem(resolution=[
                ResolutionStep(at=DONT_CARE_MOMENT, action="Restarted io-shop",
                               by="Argus", has_a_way_back=False,
                               outcome="no change", label="M1")])
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, some_resolution)
        ) \
        .then(
            the_answer_was((f'{some_resolution.by}: resolved it from {some_resolution.channel} '
                            f'- "{some_resolution.note}"',
                            "Argus: restarted io-shop - no change"))
        )


@pytest.mark.unit
def test_a_person_s_resolution_with_nothing_else_done_is_the_whole_list() -> None:
    # Not "nothing was done to end it": the person ended it.
    some_resolution = ReportedResolution(by="Dana Kuki", channel="PagerDuty",
                                         at=DONT_CARE_MOMENT, note=None)

    Scenario() \
        .given(
            some_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, some_resolution)
        ) \
        .then(
            the_answer_was((f"{some_resolution.by}: resolved it from {some_resolution.channel}",))
        )


@pytest.mark.unit
def test_the_draft_fix_follows_the_actions_and_is_said_as_a_draft() -> None:
    # A draft changes nothing running; said as anything more, a reader takes
    # the cause for fixed.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                resolution=[ResolutionStep(at=DONT_CARE_MOMENT, action="Turned it off",
                                           by="Argus", has_a_way_back=True,
                                           outcome="recovered", label="M1")],
                pull_request=SOME_FIX)
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus: turned it off - recovered",
                            f"Argus: proposed a fix, {SOME_FIX.name} - opened as a draft"))
        )


@pytest.mark.unit
def test_a_recommendation_not_taken_comes_last() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(recommended_action="Revert the pricing flag")
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Argus declined to act, and recommends: revert the pricing flag",))
        )


@pytest.mark.unit
def test_where_nothing_was_done_the_list_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem()
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Nothing was done to end it.",))
        )


@pytest.mark.unit
def test_a_disproven_alarm_needed_nothing_doing() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(disproven_at=DONT_CARE_MOMENT)
        ) \
        .when(
            lambda: the_resolution_list(some_postmortem, None)
        ) \
        .then(
            the_answer_was(("Nothing needed doing: the alarm was disproven.",))
        )
