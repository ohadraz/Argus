"""What an action was for and whether it left something to put back, said as
every place showing it says it."""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from narration import for_the_candidate, whether_it_can_be_put_back

SOME_LABEL = "C3"


@pytest.mark.unit
def test_which_candidate_an_action_was_for_is_said_by_its_label() -> None:
    # The page's resolution and the brief the model writes from both say it,
    # and two spellings of one fact read as two facts.
    Scenario() \
        .when(
            lambda: for_the_candidate(SOME_LABEL)
        ) \
        .then(
            the_answer_was(f"for {SOME_LABEL}")
        )


@pytest.mark.parametrize(("has_a_way_back", "said"), [(True, "can be put back"),
                                                      (False, "nothing to put back")])
@pytest.mark.unit
def test_whether_an_action_can_be_put_back_is_said_without_the_tier_s_words(
        has_a_way_back: bool, said: str) -> None:
    # Not "reversible" and "irreversible": those two name the autonomy tier, and
    # a restart - pre-authorised, taken unasked - shown as irreversible read as
    # Argus having broken its own rule. What the record holds is whether there is
    # anything to put back, and the page and the brief both say it.
    Scenario() \
        .when(
            lambda: whether_it_can_be_put_back(has_a_way_back, left_behind_known=True)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.parametrize(("has_a_way_back", "said"), [
    (True, "can be put back"),
    (False, "not known whether anything is left to put back")
])
@pytest.mark.unit
def test_an_action_nobody_can_account_for_is_not_said_to_leave_nothing_to_put_back(
        has_a_way_back: bool, said: str) -> None:
    # A refusal whose change request's answer was lost may have changed
    # something nobody recorded, and "nothing to put back" beside "not known
    # whether anything was changed" contradicts itself. What it does carry can
    # still be put back.
    Scenario() \
        .when(
            lambda: whether_it_can_be_put_back(has_a_way_back, left_behind_known=False)
        ) \
        .then(
            the_answer_was(said)
        )
