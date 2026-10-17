"""A revision said short: as git abbreviates it, and as long as it takes to
name it alone among the revisions an incident read.

One rule in one place, because the postmortem, the dashboard and the channel
each say a revision, and two shortenings are two chances to disagree.
"""

from __future__ import annotations

import pytest
from argus_core import short_form
from argus_testkit import Scenario, the_answer_was

# Two revisions starting nothing alike.
SOME_REVISION = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
SOME_OTHER_REVISION = "4c810f22894e612ced87f5ee3f3062dfeb785050"

# One sharing the first's seven characters and parting from it at the eighth.
SOME_RIVAL = "26f1d7e90000000000000000000000000000000a"

SOME_SHORT_FORM = SOME_REVISION[:7]


@pytest.mark.unit
def test_a_revision_is_said_in_seven_characters_as_git_abbreviates_it() -> None:
    Scenario() \
        .when(
            lambda: short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(SOME_SHORT_FORM)
        )


@pytest.mark.unit
def test_a_revision_another_starts_like_is_said_as_long_as_it_takes_to_tell_them_apart() -> None:
    Scenario() \
        .when(
            lambda: short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_RIVAL}))
        ) \
        .then(
            the_answer_was(SOME_REVISION[:8])
        )


@pytest.mark.unit
def test_a_short_form_and_the_whole_revision_it_names_are_one_revision_not_two() -> None:
    # A change's short form beside a candidate naming the same revision whole -
    # or a candidate's short form beside the change's whole one - are two names
    # for one revision, and neither makes the other longer. Taken for rivals,
    # the short one could never be told apart from the whole, however long.
    Scenario() \
        .when(
            lambda: (short_form(SOME_SHORT_FORM, frozenset({SOME_SHORT_FORM, SOME_REVISION})),
                     short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_REVISION[:9]})))
        ) \
        .then(
            the_answer_was((SOME_SHORT_FORM, SOME_SHORT_FORM))
        )
