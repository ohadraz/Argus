"""Whether it is finished: Google's five review checks, the three Argus checks
met or not, and the two left for a person - crossed until a person meets them,
and said to be theirs rather than failed.

Each case is one postmortem and what the checklist says.
"""

from __future__ import annotations

import pytest
from argus_core.models import ReviewCriterion
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.review import ReviewRow, the_review

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_each_check_is_ticked_crossed_or_left_for_a_person() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(review=[
                ReviewCriterion(criterion="impact assessed", met=True),
                ReviewCriterion(criterion="root-cause analysis complete", met=False),
                ReviewCriterion(criterion="reviewed and shared", met=None)])
        ) \
        .when(
            lambda: the_review(some_postmortem).rows
        ) \
        .then(
            the_answer_was((
                ReviewRow(criterion="impact assessed", met="yes", mark="✓", meaning="met",
                          because=None),
                ReviewRow(criterion="root-cause analysis complete", met="no", mark="✗",
                          meaning="not met", because=None),
                ReviewRow(criterion="reviewed and shared", met="left", mark="✗",
                          meaning="for a person", because=None))))


@pytest.mark.unit
def test_a_check_left_for_a_person_says_what_they_would_do() -> None:
    # A check the analysis could not meet alone is left for a person, and the
    # row says what that person would do - "for a person" alone reads as the
    # two checks only people ever meet. Said apart from the mark's meaning: the
    # meaning is a word that fits beside the check, and the reason a sentence
    # that has to wrap.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(review=[
                ReviewCriterion(criterion="root-cause analysis complete", met=None,
                                because="the cause rests on F1, a reading of the source "
                                        "nothing ran")])
        ) \
        .when(
            lambda: the_review(some_postmortem).rows
        ) \
        .then(
            the_answer_was((
                ReviewRow(criterion="root-cause analysis complete", met="left", mark="✗",
                          meaning="for a person",
                          because="the cause rests on F1, a reading of the source nothing "
                                  "ran"),)))


@pytest.mark.unit
def test_a_document_never_reviewed_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(review=[])
        ) \
        .when(
            lambda: the_review(some_postmortem).absent
        ) \
        .then(
            the_answer_was("Not reviewed."))
