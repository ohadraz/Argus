from __future__ import annotations

import pytest
from argus_core.anthropic_llm import Explanation, MalformedVerdict, Verdict
from argus_core.ids import new_id
from argus_core.models.cause import CauseType

"""The wire shape the model fills in, and where it becomes a hypothesis.

`to_hypotheses` is the single point at which the model's answer meets the
domain, so it is the single point at which an answer the domain refuses has to
be caught. Everything here is offline - no client, no recording - because what
is under test is the join, not the call.

The model answers with its best explanation and, where the same evidence
supports them, the others it weighed. They are the same shape - an
`Explanation` - because they are the same kind of thing; only one of them is
also the carrier of the rest.
"""


@pytest.mark.unit
def test_the_subject_the_model_named_reaches_the_hypothesis() -> None:
    # The whole reason the field exists: Mitigation reads it. A verdict that
    # carried the flag only in its prose is one Mitigation has to re-derive.
    some_flag = "monthly-spend-feature"

    candidates = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject=some_flag
    ).to_hypotheses(new_id())

    assert candidates[0].subject == some_flag


@pytest.mark.unit
def test_a_cause_that_names_no_subject_becomes_a_hypothesis_without_one() -> None:
    # Not every cause has a subject this system can name - a bad deployment is
    # a real cause with nothing to put here - so leaving it out is an answer,
    # not an omission to be filled in.
    candidates = a_verdict_naming(
        CauseType.BAD_DEPLOYMENT, subject=None
    ).to_hypotheses(new_id())

    assert candidates[0].subject is None


@pytest.mark.unit
def test_the_verdict_belongs_to_the_incident_it_is_joined_to() -> None:
    some_incident_id = new_id()

    verdict = a_verdict_naming(CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag")
    verdict = verdict.model_copy(
        update={"alternatives": [an_explanation_at(0.5)]}
    )

    candidates = verdict.to_hypotheses(some_incident_id)

    assert [candidate.incident_id for candidate in candidates] == [
        some_incident_id,
        some_incident_id,
    ]


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
        undetermined.to_hypotheses(new_id())


@pytest.mark.unit
def test_a_verdict_with_no_alternatives_yields_one_candidate() -> None:
    # The shape every committed recording has, and the shape a model answers
    # with when the evidence supports one explanation. It must stay the
    # ordinary case, not a degenerate one.
    candidates = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag"
    ).to_hypotheses(new_id())

    assert len(candidates) == 1


@pytest.mark.unit
def test_every_alternative_becomes_a_candidate() -> None:
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag"
    ).model_copy(
        update={"alternatives": [an_explanation_at(0.6), an_explanation_at(0.4)]}
    )

    assert len(verdict.to_hypotheses(new_id())) == 3


@pytest.mark.unit
def test_candidates_come_back_in_descending_confidence() -> None:
    # The model is asked for its ordering and its numbers. Where they disagree
    # the numbers win, because the numbers are what the mitigate threshold
    # already reads - a rank is then a property of the answer rather than of
    # how the model happened to serialize it.
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag", confidence=0.70
    ).model_copy(update={"alternatives": [an_explanation_at(0.90)]})

    confidences = [candidate.confidence for candidate in verdict.to_hypotheses(new_id())]

    assert confidences == [0.90, 0.70]


@pytest.mark.unit
def test_equal_confidences_keep_the_order_the_model_gave() -> None:
    some_confidence = 0.80
    first_named = an_explanation_at(some_confidence, subject="named-first")
    second_named = an_explanation_at(some_confidence, subject="named-second")
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="the-primary", confidence=some_confidence
    ).model_copy(update={"alternatives": [first_named, second_named]})

    subjects = [candidate.subject for candidate in verdict.to_hypotheses(new_id())]

    assert subjects == ["the-primary", "named-first", "named-second"]


@pytest.mark.unit
def test_candidates_are_ranked_in_the_order_they_come_back() -> None:
    # The rank is persisted, and rows come back from a table in no order at
    # all - so the position has to survive as data, not as list order.
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag", confidence=0.90
    ).model_copy(update={"alternatives": [an_explanation_at(0.60)]})

    assert [candidate.rank for candidate in verdict.to_hypotheses(new_id())] == [1, 2]


@pytest.mark.unit
def test_an_incoherent_alternative_makes_the_whole_verdict_malformed() -> None:
    # An alternative is a hypothesis in waiting, held to the rules every
    # hypothesis is. Dropping the bad one and keeping the rest would be this
    # layer deciding which parts of a model's answer to believe.
    an_alternative_naming_nothing = Explanation(
        summary="some summary",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
        subject="some-flag",
    )
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag"
    ).model_copy(update={"alternatives": [an_alternative_naming_nothing]})

    with pytest.raises(MalformedVerdict):
        verdict.to_hypotheses(new_id())


@pytest.mark.unit
def test_an_alternative_with_no_confidence_sorts_last() -> None:
    # It names no cause either - the two travel together - so it is the one
    # thing on the list nothing can be done about. It is kept, because it is
    # still something the model said, and ordered last, because ordering it
    # anywhere else would put an unactionable answer above an actionable one.
    an_undetermined_alternative = Explanation(
        summary="some summary",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
        subject=None,
    )
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag", confidence=0.10
    ).model_copy(update={"alternatives": [an_undetermined_alternative]})

    candidates = verdict.to_hypotheses(new_id())

    assert [candidate.confidence for candidate in candidates] == [0.10, None]


@pytest.mark.unit
def test_a_verdict_longer_than_the_walk_can_try_keeps_the_most_confident() -> None:
    # How long a verdict is, is the model's choice; what it costs is the walk's
    # problem. Every candidate is an experiment against production and a wait
    # for the service to answer, and the graph's traversal budget is derived
    # from this number - so it is a number, not a matter of how talkative one
    # answer happened to be. The dropped ones are the least confident, which
    # are also the ones the mitigate threshold was likeliest to refuse.
    all_a_walk_will_try = 2
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="the-primary", confidence=0.99
    ).model_copy(
        update={
            "alternatives": [
                an_explanation_at(0.80, subject="the-runner-up"),
                an_explanation_at(0.70, subject="never-reached"),
            ]
        }
    )

    candidates = verdict.to_hypotheses(new_id(), limit=all_a_walk_will_try)

    assert [candidate.subject for candidate in candidates] == [
        "the-primary",
        "the-runner-up",
    ]


@pytest.mark.unit
def test_a_verdict_shorter_than_the_limit_is_left_alone() -> None:
    # The cap is a ceiling, not a quota - an investigation that honestly had
    # one explanation must not be padded, and one that had two must not look
    # like it was cut short.
    a_limit_no_verdict_here_reaches = 5
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag"
    ).model_copy(update={"alternatives": [an_explanation_at(0.60)]})

    candidates = verdict.to_hypotheses(new_id(), limit=a_limit_no_verdict_here_reaches)

    assert len(candidates) == 2


@pytest.mark.unit
def test_an_incoherent_explanation_past_the_limit_still_fails_the_whole_verdict() -> None:
    # The limit is about what the walk will try, not about what the adapter
    # will look at. An incoherent answer that escaped notice by being the least
    # confident one on a long list would make the rule above depend on how many
    # alternatives the model happened to offer.
    all_a_walk_will_try = 1
    an_alternative_naming_nothing = Explanation(
        summary="some summary",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
        subject="some-flag",
    )
    verdict = a_verdict_naming(
        CauseType.FEATURE_FLAG_TOGGLE, subject="some-flag", confidence=0.99
    ).model_copy(update={"alternatives": [an_alternative_naming_nothing]})

    with pytest.raises(MalformedVerdict):
        verdict.to_hypotheses(new_id(), limit=all_a_walk_will_try)


def a_verdict_naming(
    cause_type: CauseType, subject: str | None, confidence: float = 0.9
) -> Verdict:
    return Verdict(
        summary="some summary",
        cause_type=cause_type,
        confidence=confidence,
        supporting_evidence=["some log line"],
        subject=subject,
    )


def an_explanation_at(confidence: float, subject: str | None = None) -> Explanation:
    return Explanation(
        summary="some summary",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=["some log line"],
        subject=subject,
    )
