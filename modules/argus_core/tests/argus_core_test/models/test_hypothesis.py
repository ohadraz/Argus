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
def test_a_confidence_above_one_is_rejected() -> None:
    # A probability the model wrote outside its own scale. The tool schema
    # cannot say so - a strict schema takes no bounds on a number - so the only
    # place this can be caught is here, and it has to be, because everything
    # downstream reads the figure as a probability and shows it to a human.
    some_confidence_off_the_scale = 1.4

    with pytest.raises(ValidationError, match="confidence"):
        an_investigated_hypothesis(
            cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_confidence_off_the_scale
        )


@pytest.mark.unit
def test_a_confidence_below_zero_is_rejected() -> None:
    some_negative_confidence = -0.1

    with pytest.raises(ValidationError, match="confidence"):
        an_investigated_hypothesis(
            cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_negative_confidence
        )


@pytest.mark.unit
def test_certainty_and_impossibility_are_both_inside_the_scale() -> None:
    # The ends belong to it: 1.0 is "the evidence records the cause directly",
    # which the prompt asks for by name, and a bound that excluded it would
    # reject the best answer the model can give.
    certain = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=1.0
    )
    impossible = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=0.0
    )

    assert (certain.confidence, impossible.confidence) == (1.0, 0.0)


@pytest.mark.unit
def test_neither_a_cause_nor_a_confidence_is_accepted() -> None:
    hypothesis = an_investigated_hypothesis(cause_type=None, confidence=None)

    assert hypothesis.cause_type is None


@pytest.mark.unit
def test_an_undetermined_hypothesis_is_never_confident_enough() -> None:
    hypothesis = an_investigated_hypothesis(cause_type=None, confidence=None)

    assert not hypothesis.is_confident_enough(0.0)


@pytest.mark.unit
def test_a_hypothesis_exactly_at_the_threshold_is_confident_enough() -> None:
    some_threshold = 0.75

    hypothesis = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_threshold
    )

    assert hypothesis.is_confident_enough(some_threshold)


@pytest.mark.unit
def test_a_hypothesis_just_below_the_threshold_is_not_confident_enough() -> None:
    some_threshold = 0.75

    hypothesis = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=some_threshold - 0.01
    )

    assert not hypothesis.is_confident_enough(some_threshold)


@pytest.mark.unit
def test_two_hypotheses_built_the_same_way_have_different_ids() -> None:
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


@pytest.mark.unit
def test_a_hypothesis_carries_the_subject_its_cause_names() -> None:
    # The whole point of the field: what the Investigator blamed survives as a
    # value a later phase can act on, instead of only as words in `summary`.
    some_flag = "monthly-spend-feature"

    hypothesis = an_investigated_hypothesis(
        cause_type=CauseType.FEATURE_FLAG_TOGGLE, confidence=0.9, subject=some_flag
    )

    assert hypothesis.subject == some_flag


@pytest.mark.unit
def test_a_hypothesis_that_names_no_subject_has_none() -> None:
    # A cause need not have a subject this system can name - a bad deployment
    # is a real cause with nothing to put here yet - so the field is absent
    # rather than empty, and callers get one thing to check instead of two.
    hypothesis = an_investigated_hypothesis(
        cause_type=CauseType.BAD_DEPLOYMENT, confidence=0.9
    )

    assert hypothesis.subject is None


@pytest.mark.unit
def test_a_subject_without_a_cause_is_rejected() -> None:
    # "I blame monthly-spend-feature, for nothing" is not a conclusion. It is
    # the same incoherence the cause/confidence rule already refuses, one field
    # over, and left alone it would reach Mitigation as a flag to act on with
    # no diagnosis behind it.
    dont_care_flag = "monthly-spend-feature"

    with pytest.raises(ValidationError, match="subject"):
        Hypothesis(
            incident_id=new_id(),
            summary="some summary",
            cause_type=None,
            confidence=None,
            supporting_evidence=[],
            subject=dont_care_flag,
        )


def an_investigated_hypothesis(cause_type: CauseType | None,
                               confidence: float | None,
                               subject: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=new_id(),
        summary="some summary",
        cause_type=cause_type,
        confidence=confidence,
        supporting_evidence=["some log line"],
        subject=subject,
    )
