from __future__ import annotations

import pytest
from argus_core.anthropic_llm import MalformedVerdict, Verdict
from argus_core.ids import new_id
from argus_core.models.cause import CauseType

"""The wire shape the model fills in, and where it becomes a hypothesis.

`to_hypothesis` is the single point at which the model's answer meets the
domain, so it is the single point at which an answer the domain refuses has to
be caught. Everything here is offline - no client, no recording - because what
is under test is the join, not the call.
"""


@pytest.mark.unit
def test_the_subject_the_model_named_reaches_the_hypothesis() -> None:
    # The whole reason the field exists: Mitigation reads it. A verdict that
    # carried the flag only in its prose is one Mitigation has to re-derive.
    some_flag = "monthly-spend-feature"

    hypothesis = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject=some_flag
    ).to_hypothesis(new_id())

    assert hypothesis.subject == some_flag


@pytest.mark.unit
def test_a_cause_that_names_no_subject_becomes_a_hypothesis_without_one() -> None:
    # Not every cause has a subject this system can name - a bad deployment is
    # a real cause with nothing to put here - so leaving it out is an answer,
    # not an omission to be filled in.
    hypothesis = a_verdict_naming(
        CauseType.BAD_DEPLOYMENT, subject=None
    ).to_hypothesis(new_id())

    assert hypothesis.subject is None


@pytest.mark.unit
def test_the_verdict_belongs_to_the_incident_it_is_joined_to() -> None:
    some_incident_id = new_id()

    hypothesis = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="monthly-spend-feature"
    ).to_hypothesis(some_incident_id)

    assert hypothesis.incident_id == some_incident_id


@pytest.mark.unit
def test_a_subject_named_for_no_cause_is_malformed() -> None:
    # The domain refuses it, and this is where that refusal has to surface as
    # the adapter's own error - otherwise a pydantic failure escapes to a
    # caller that was told to expect `VerdictNotReached` and nothing else.
    dont_care_flag = "monthly-spend-feature"
    undetermined = Verdict(
        summary="some summary",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
        subject=dont_care_flag,
    )

    with pytest.raises(MalformedVerdict):
        undetermined.to_hypothesis(new_id())


def a_verdict_naming(cause_type: CauseType, subject: str | None) -> Verdict:
    some_confidence = 0.9

    return Verdict(
        summary="some summary",
        cause_type=cause_type,
        confidence=some_confidence,
        supporting_evidence=["some log line"],
        subject=subject,
    )
