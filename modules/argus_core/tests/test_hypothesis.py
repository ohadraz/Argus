from __future__ import annotations

import pytest
from argus_core.ids import new_id
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from pydantic import ValidationError


@pytest.mark.unit
def test_a_cause_without_a_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError, match="cause"):
        Hypothesis(
            incident_id=new_id(),
            summary="some summary",
            cause_type=CauseType.FEATURE_FLAG_TOGGLE,
            confidence=None,
            supporting_evidence=[],
        )


@pytest.mark.unit
def test_a_confidence_without_a_cause_is_rejected() -> None:
    some_confidence = 0.9

    with pytest.raises(ValidationError, match="cause"):
        Hypothesis(
            incident_id=new_id(),
            summary="some summary",
            cause_type=None,
            confidence=some_confidence,
            supporting_evidence=[],
        )


@pytest.mark.unit
def test_a_cause_with_a_confidence_is_accepted() -> None:
    some_confidence = 0.9

    hypothesis = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_confidence
    )

    assert hypothesis.confidence == some_confidence


@pytest.mark.unit
def test_neither_a_cause_nor_a_confidence_is_accepted() -> None:
    hypothesis = an_investigated_hypothesis(cause_type=None, confidence=None)

    assert hypothesis.cause_type is None


@pytest.mark.unit
def test_an_undetermined_hypothesis_is_never_confident_enough() -> None:
    lowest_possible_threshold = 0.0
    undetermined = an_investigated_hypothesis(cause_type=None, confidence=None)

    assert not undetermined.is_confident_enough(lowest_possible_threshold)


@pytest.mark.unit
def test_a_hypothesis_exactly_at_the_threshold_is_confident_enough() -> None:
    some_threshold = 0.75
    exactly_at_the_threshold = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_threshold
    )

    assert exactly_at_the_threshold.is_confident_enough(some_threshold)


@pytest.mark.unit
def test_a_hypothesis_just_below_the_threshold_is_not_confident_enough() -> None:
    some_threshold = 0.75
    some_below_threshold = some_threshold - 0.01
    just_below_the_threshold = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_below_threshold
    )

    assert not just_below_the_threshold.is_confident_enough(some_threshold)


@pytest.mark.unit
def test_two_hypotheses_built_the_same_way_have_different_ids() -> None:
    # Identity belongs to the entity, not to the table it later lands in - a
    # hypothesis can be referenced and logged before anything is persisted.
    one = an_investigated_hypothesis(cause_type=None, confidence=None)
    another = an_investigated_hypothesis(cause_type=None, confidence=None)

    assert one.id != another.id


@pytest.mark.unit
def test_a_hypothesis_keeps_the_id_it_was_given() -> None:
    some_id = new_id()

    hypothesis = Hypothesis(
        id=some_id,
        incident_id=new_id(),
        summary="some summary",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
    )

    assert hypothesis.id == some_id


def an_investigated_hypothesis(cause_type: CauseType | None,
                               confidence: float | None) -> Hypothesis:
    return Hypothesis(
        incident_id=new_id(),
        summary="some summary",
        cause_type=cause_type,
        confidence=confidence,
        supporting_evidence=["some log line"],
    )
