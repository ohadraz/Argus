"""The response's minutes, held by title.

Kept by title rather than summed, because a pay band prices a title: whatever
prices the response later prices these rows, and a total that has added a
senior engineer's hour to a junior's cannot be priced at all.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import TitleMinutes
from postmortem_writing.effort import minutes_by_title
from postmortem_writing.sources import EngagedResponder

SOME_TITLE = "Site Reliability Engineer"
SOME_OTHER_TITLE = "Senior Software Engineer"


@pytest.mark.unit
def test_the_minutes_are_held_by_title_in_the_order_each_title_first_responded() -> None:
    some_minutes, some_more_minutes, some_other_minutes = 15, 5, 10

    Scenario() \
        .given(
            some_responders := [EngagedResponder(minutes=some_minutes, job_title=SOME_TITLE),
                                EngagedResponder(minutes=some_other_minutes,
                                                 job_title=SOME_OTHER_TITLE),
                                EngagedResponder(minutes=some_more_minutes, job_title=SOME_TITLE)]
        ) \
        .when(
            lambda: minutes_by_title(some_responders)
        ) \
        .then(
            the_answer_was([
                TitleMinutes(title=SOME_TITLE, responders=2,
                             minutes=some_minutes + some_more_minutes),
                TitleMinutes(title=SOME_OTHER_TITLE, responders=1, minutes=some_other_minutes)
            ])
        )


@pytest.mark.unit
def test_responders_with_no_title_recorded_are_a_row_of_their_own() -> None:
    # Left out, the rows would no longer add up to everyone who responded, and
    # whatever prices them would price the response short.
    some_minutes, some_other_minutes = 15, 10

    Scenario() \
        .given(
            some_responders := [EngagedResponder(minutes=some_minutes, job_title=SOME_TITLE),
                                EngagedResponder(minutes=some_other_minutes, job_title=None)]
        ) \
        .when(
            lambda: minutes_by_title(some_responders)
        ) \
        .then(
            the_answer_was([
                TitleMinutes(title=SOME_TITLE, responders=1, minutes=some_minutes),
                TitleMinutes(title=None, responders=1, minutes=some_other_minutes)
            ])
        )
