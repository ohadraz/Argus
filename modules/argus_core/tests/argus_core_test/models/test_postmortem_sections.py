"""The sections a postmortem has beyond its figures, and what each refuses to
hold.

The shape is the agent's to fill, so the cases here are the states no section
may be written in - a pair of fields that say two things nobody could have
measured together - and the few things a section says of itself, which every
place showing it has to say alike.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import (
    CandidateConsidered,
    Detection,
    HypothesisConsidered,
    whether_it_can_be_put_back,
)
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from pydantic import ValidationError

DONT_CARE_MOMENT = datetime(2026, 10, 19, 0, 12, tzinfo=UTC)


@pytest.mark.unit
def test_detection_holding_a_rule_s_wait_and_saying_it_could_not_be_read_is_refused() -> None:
    # A wait that was read is not one that could not be: the page would say
    # both, and a reader could believe neither.
    Scenario() \
        .when(
            attempting(
                lambda: Detection(alerted_at=DONT_CARE_MOMENT, rule="dont care", onset_at=None,
                                  gap=None, rule_waits=timedelta(minutes=5),
                                  rule_wait_unread=True)
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_merged_candidate_not_the_one_tested_has_the_result_as_the_tested_one_s() -> None:
    # The page and the brief both say it, and in one spelling: two wordings of
    # one fact read as two facts.
    Scenario() \
        .given(
            hypothesis := _a_merged_hypothesis(result="confirmed", decided_by="C1")
        ) \
        .when(
            lambda: hypothesis.result_of(hypothesis.members[1])
        ) \
        .then(
            the_answer_was("confirmed, as tested for C1")
        )


@pytest.mark.parametrize(("decided_by", "result"), [("C1", "confirmed"),
                                                    (None, "never tried")])
@pytest.mark.unit
def test_a_merged_candidate_tested_itself_or_where_none_was_has_the_result_bare(
        decided_by: str | None, result: str) -> None:
    # Its own test is no other's to credit, and with no test there is none.
    Scenario() \
        .given(
            hypothesis := _a_merged_hypothesis(result=result, decided_by=decided_by)
        ) \
        .when(
            lambda: hypothesis.result_of(hypothesis.members[0])
        ) \
        .then(
            the_answer_was(result)
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
            lambda: whether_it_can_be_put_back(has_a_way_back)
        ) \
        .then(
            the_answer_was(said)
        )


def _a_merged_hypothesis(result: str, decided_by: str | None) -> HypothesisConsidered:
    return HypothesisConsidered(
        summary="dont care", confidence=None, result=result, label="C1", also=["C2"],
        members=[CandidateConsidered(label="C1", summary="dont care", confidence=None,
                                     failure_mode=None),
                 CandidateConsidered(label="C2", summary="dont care", confidence=None,
                                     failure_mode=None)],
        decided_by=decided_by)
