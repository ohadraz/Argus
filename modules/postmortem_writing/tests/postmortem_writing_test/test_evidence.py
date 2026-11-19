"""What the evidence a postmortem is written from works out of itself - when
Argus first changed anything.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import ActionProgress

from postmortem_writing_test.framework.builders import STARTED_AT, an_action, an_evidence_bundle

# Two moments an action was taken at, the earlier first.
SOME_EARLIER_MOMENT = STARTED_AT + timedelta(minutes=2)
SOME_LATER_MOMENT = SOME_EARLIER_MOMENT + timedelta(minutes=3)
DONT_CARE_ACTION = "Reverted the feature flag dont-care"


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.PERFORMED, ActionProgress.PUTTING_BACK],
                         ids=["made", "owed-back"])
def test_argus_first_acted_when_it_first_made_a_change_however_far_the_change_got(
        progress: ActionProgress) -> None:
    # A refuted change a person ended the incident before putting back was made
    # all the same - its put-back is what never ran. Left out, the minute Argus
    # first acted would be a later action's, and a recovery before it would be
    # credited to nothing Argus did.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(DONT_CARE_ACTION, taken_at=SOME_EARLIER_MOMENT, progress=progress),
                an_action(DONT_CARE_ACTION, taken_at=SOME_LATER_MOMENT,
                          progress=ActionProgress.PERFORMED)])
        ) \
        .when(
            lambda: evidence.first_acted_at
        ) \
        .then(
            the_answer_was(SOME_EARLIER_MOMENT)
        )


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.NOT_PERFORMED, ActionProgress.CLAIMED,
                                      ActionProgress.UNKNOWN],
                         ids=["not-performed", "claimed", "unknown"])
def test_an_action_not_known_to_have_changed_anything_is_not_when_argus_first_acted(
        progress: ActionProgress) -> None:
    # Said as the minute Argus acted, either says a change was made.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(DONT_CARE_ACTION, taken_at=SOME_EARLIER_MOMENT, progress=progress),
                an_action(DONT_CARE_ACTION, taken_at=SOME_LATER_MOMENT,
                          progress=ActionProgress.PERFORMED)])
        ) \
        .when(
            lambda: evidence.first_acted_at
        ) \
        .then(
            the_answer_was(SOME_LATER_MOMENT)
        )
