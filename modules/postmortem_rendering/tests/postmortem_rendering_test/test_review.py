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
                ReviewRow(criterion="impact assessed", met="yes", mark="✓", meaning="met"),
                ReviewRow(criterion="root-cause analysis complete", met="no", mark="✗",
                          meaning="not met"),
                ReviewRow(criterion="reviewed and shared", met="left", mark="✗",
                          meaning="for a person"))))


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
