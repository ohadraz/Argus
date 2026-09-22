"""What a hypothesis has to say together, and what it may leave unsaid.

The Investigator's conclusion, and the one value a later phase acts on. Almost
every rule here is about coherence between two fields rather than about either
alone: a cause with no confidence, a confidence with no cause, a subject
nothing is blamed for, half a transition. Each of those is a sentence that
parses and means nothing, and each would reach Mitigation as an instruction.

The rest is about what may be absent. A cause this system cannot name a
subject for is a real cause, so `subject` is missing rather than empty - one
thing for a caller to check instead of two.
"""

from __future__ import annotations

import pytest
from argus_core.ids import new_id
from argus_core.models.evidence import Evidence
from argus_core.models.failure_mode import FailureMode
from argus_core.models.hypothesis import Hypothesis
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from pydantic import ValidationError

SOME_SUMMARY = "some summary"
SOME_FLAG = "monthly-spend-feature"


@pytest.mark.unit
def test_a_cause_without_a_confidence_is_rejected() -> None:
    Scenario() \
        .given(
            a_cause_nobody_put_a_figure_on := FailureMode.FEATURE_FLAG_TOGGLE
        ) \
        .when(
            attempting(
                lambda: Hypothesis(
                    incident_id=new_id(),
                    summary=SOME_SUMMARY,
                    failure_mode=a_cause_nobody_put_a_figure_on,
                    confidence=None,
                    supporting_evidence=[]
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("cause")
            )
        )


@pytest.mark.unit
def test_a_confidence_without_a_cause_is_rejected() -> None:
    Scenario() \
        .given(
            some_confidence := 0.9
        ) \
        .when(
            attempting(
                lambda: Hypothesis(
                    incident_id=new_id(),
                    summary=SOME_SUMMARY,
                    failure_mode=None,
                    confidence=some_confidence,
                    supporting_evidence=[]
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("cause")
            )
        )


@pytest.mark.unit
def test_a_cause_with_a_confidence_is_accepted() -> None:
    Scenario() \
        .given(
            some_confidence := 0.9
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=some_confidence
            )
        ) \
        .then(
            _the_confidence_was(some_confidence)
        )


@pytest.mark.unit
def test_a_confidence_above_one_is_rejected() -> None:
    # A probability the model wrote outside its own scale. The tool schema
    # cannot say so - a strict schema takes no bounds on a number - so the only
    # place this can be caught is here, and it has to be, because everything
    # downstream reads the figure as a probability and shows it to a human.
    Scenario() \
        .given(
            some_confidence_off_the_scale := 1.4
        ) \
        .when(
            attempting(
                lambda: an_investigated_hypothesis(
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                    confidence=some_confidence_off_the_scale
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("confidence")
            )
        )


@pytest.mark.unit
def test_a_confidence_below_zero_is_rejected() -> None:
    Scenario() \
        .given(
            some_negative_confidence := -0.1
        ) \
        .when(
            attempting(
                lambda: an_investigated_hypothesis(
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                    confidence=some_negative_confidence
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("confidence")
            )
        )


@pytest.mark.unit
def test_certainty_and_impossibility_are_both_inside_the_scale() -> None:
    # The ends belong to it: 1.0 is "the evidence records the cause directly",
    # which the prompt asks for by name, and a bound that excluded it would
    # reject the best answer the model can give.
    Scenario() \
        .given(
            both_ends_of_the_scale := (1.0, 0.0)
        ) \
        .when(
            lambda: tuple(
                an_investigated_hypothesis(
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=end
                ).confidence
                for end in both_ends_of_the_scale
            )
        ) \
        .then(
            _the_confidences_were(both_ends_of_the_scale)
        )


@pytest.mark.unit
def test_neither_a_cause_nor_a_confidence_is_accepted() -> None:
    Scenario() \
        .given(
            an_investigation_that_concluded_nothing := (None, None)
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=an_investigation_that_concluded_nothing[0],
                confidence=an_investigation_that_concluded_nothing[1]
            )
        ) \
        .then(
            _the_cause_was(None)
        )


@pytest.mark.unit
def test_an_undetermined_hypothesis_is_never_confident_enough() -> None:
    Scenario() \
        .given(
            an_undetermined := an_investigated_hypothesis(failure_mode=None, confidence=None)
        ) \
        .when(
            lambda: an_undetermined.is_confident_enough(0.0)
        ) \
        .then(
            _the_threshold_was_not_cleared()
        )


@pytest.mark.unit
def test_a_hypothesis_exactly_at_the_threshold_is_confident_enough() -> None:
    Scenario() \
        .given(
            some_threshold := 0.75
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=some_threshold
            ).is_confident_enough(some_threshold)
        ) \
        .then(
            _the_threshold_was_cleared()
        )


@pytest.mark.unit
def test_a_hypothesis_just_below_the_threshold_is_not_confident_enough() -> None:
    Scenario() \
        .given(
            some_threshold := 0.75
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                confidence=some_threshold - 0.01
            ).is_confident_enough(some_threshold)
        ) \
        .then(
            _the_threshold_was_not_cleared()
        )


@pytest.mark.unit
def test_two_hypotheses_built_the_same_way_have_different_ids() -> None:
    Scenario() \
        .given(
            built_the_same_way := {"failure_mode": None, "confidence": None}
        ) \
        .when(
            lambda: (
                an_investigated_hypothesis(**built_the_same_way).id,
                an_investigated_hypothesis(**built_the_same_way).id
            )
        ) \
        .then(
            _the_two_ids_differed()
        )


@pytest.mark.unit
def test_a_hypothesis_keeps_the_id_it_was_given() -> None:
    Scenario() \
        .given(
            some_id := new_id()
        ) \
        .when(
            lambda: Hypothesis(
                id=some_id,
                incident_id=new_id(),
                summary=SOME_SUMMARY,
                failure_mode=None,
                confidence=None,
                supporting_evidence=[]
            )
        ) \
        .then(
            _the_id_was(some_id)
        )


@pytest.mark.unit
def test_a_hypothesis_carries_the_subject_its_cause_names() -> None:
    # The whole point of the field: what the Investigator blamed survives as a
    # value a later phase can act on, instead of only as words in `summary`.
    Scenario() \
        .given(
            some_flag := SOME_FLAG
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=0.9, subject=some_flag
            )
        ) \
        .then(
            _the_subject_was(some_flag)
        )


@pytest.mark.unit
def test_a_hypothesis_that_names_no_subject_has_none() -> None:
    # A cause need not have a subject this system can name - a bad deployment
    # is a real cause with nothing to put here yet - so the field is absent
    # rather than empty, and callers get one thing to check instead of two.
    Scenario() \
        .given(
            a_cause_with_nothing_to_name := FailureMode.BAD_DEPLOYMENT
        ) \
        .when(
            lambda: an_investigated_hypothesis(
                failure_mode=a_cause_with_nothing_to_name, confidence=0.9
            )
        ) \
        .then(
            _the_subject_was(None)
        )


@pytest.mark.unit
def test_a_subject_without_a_cause_is_rejected() -> None:
    # "I blame monthly-spend-feature, for nothing" is not a conclusion. It is
    # the same incoherence the cause/confidence rule already refuses, one field
    # over, and left alone it would reach Mitigation as a flag to act on with
    # no diagnosis behind it.
    Scenario() \
        .given(
            dont_care_flag := SOME_FLAG
        ) \
        .when(
            attempting(
                lambda: Hypothesis(
                    incident_id=new_id(),
                    summary=SOME_SUMMARY,
                    failure_mode=None,
                    confidence=None,
                    supporting_evidence=[],
                    subject=dont_care_flag
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("subject")
            )
        )


@pytest.mark.unit
def test_a_hypothesis_carries_the_states_its_subject_moved_between() -> None:
    # The transition as two fields rather than as words inside `summary`. A
    # page reading it back out of the sentence has to guess which two of the
    # `on`s and `off`s in it were the states, and guesses wrong on a sentence
    # that merely uses the word.
    Scenario() \
        .given(
            the_states_it_moved_between := ("off", "on")
        ) \
        .when(
            lambda: Hypothesis(
                incident_id=new_id(),
                summary=SOME_SUMMARY,
                failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                confidence=0.9,
                supporting_evidence=[],
                subject=SOME_FLAG,
                from_state=the_states_it_moved_between[0],
                to_state=the_states_it_moved_between[1]
            )
        ) \
        .then(
            _the_transition_was(the_states_it_moved_between)
        )


@pytest.mark.unit
def test_one_state_without_the_other_is_rejected() -> None:
    # Half a transition is not one. "It moved to ON" from nothing in
    # particular is the same incoherence as a confidence with no cause, and a
    # page rendering `<s></s> → ON` would show a change out of nowhere.
    Scenario() \
        .given(
            an_arrival_from_nowhere := "on"
        ) \
        .when(
            attempting(
                lambda: Hypothesis(
                    incident_id=new_id(),
                    summary=SOME_SUMMARY,
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                    confidence=0.9,
                    supporting_evidence=[],
                    subject=SOME_FLAG,
                    from_state=None,
                    to_state=an_arrival_from_nowhere
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("state")
            )
        )


@pytest.mark.unit
def test_a_transition_without_a_subject_is_rejected() -> None:
    # Something moved from OFF to ON and the hypothesis will not say what. The
    # states are only readable as a change to the thing `subject` names, so
    # without one the page has a transition and nothing to attach it to.
    Scenario() \
        .given(
            dont_care_state := "off"
        ) \
        .when(
            attempting(
                lambda: Hypothesis(
                    incident_id=new_id(),
                    summary=SOME_SUMMARY,
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                    confidence=0.9,
                    supporting_evidence=[],
                    subject=None,
                    from_state=dont_care_state,
                    to_state="on"
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("subject")
            )
        )


def an_investigated_hypothesis(failure_mode: FailureMode | None,
                               confidence: float | None,
                               subject: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=new_id(),
        summary=SOME_SUMMARY,
        failure_mode=failure_mode,
        confidence=confidence,
        supporting_evidence=[Evidence(claim="some log line", at=None)],
        subject=subject
    )


def _the_confidence_was(expected: float | None) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        if hypothesis.confidence != expected:
            raise AssertionError(
                f"Expected a confidence of [{expected}], got [{hypothesis.confidence}]."
            )

        return True

    return assertion


def _the_confidences_were(expected: tuple[float, ...]) -> Assertion[tuple[float | None, ...]]:
    """Both ends of the scale in one assertion, so neither can fail unreported."""
    def assertion(kept: tuple[float | None, ...]) -> bool:
        if kept != expected:
            raise AssertionError(f"Expected the scale to keep {expected}, got {kept}.")

        return True

    return assertion


def _the_cause_was(expected: FailureMode | None) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        if hypothesis.failure_mode is not expected:
            raise AssertionError(
                f"Expected a cause of [{expected}], got [{hypothesis.failure_mode}]."
            )

        return True

    return assertion


def _the_subject_was(expected: str | None) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        if hypothesis.subject != expected:
            raise AssertionError(
                f"Expected a subject of [{expected}], got [{hypothesis.subject}]."
            )

        return True

    return assertion


def _the_id_was(expected: str) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        if hypothesis.id != expected:
            raise AssertionError(f"Expected the id [{expected}], got [{hypothesis.id}].")

        return True

    return assertion


def _the_two_ids_differed() -> Assertion[tuple[str, str]]:
    """That building the same hypothesis twice produced two records.

    An id is what a later phase names one candidate by, so two that shared one
    would be one candidate as far as anything downstream could tell - and the
    second conclusion would silently replace the first.
    """
    def assertion(ids: tuple[str, str]) -> bool:
        one, another = ids
        if one == another:
            raise AssertionError(f"Expected two different ids, and both were [{one}].")

        return True

    return assertion


def _the_transition_was(expected: tuple[str, str]) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        moved_between = (hypothesis.from_state, hypothesis.to_state)
        if moved_between != expected:
            raise AssertionError(f"Expected a move {expected}, got {moved_between}.")

        return True

    return assertion


def _the_threshold_was_cleared() -> Assertion[bool]:
    def assertion(confident_enough: bool) -> bool:
        if not confident_enough:
            raise AssertionError("Expected the hypothesis to clear the threshold, and it did not.")

        return True

    return assertion


def _the_threshold_was_not_cleared() -> Assertion[bool]:
    def assertion(confident_enough: bool) -> bool:
        if confident_enough:
            raise AssertionError(
                "Expected the hypothesis to fall short of the threshold, and it cleared it."
            )

        return True

    return assertion
