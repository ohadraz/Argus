"""The spelling of an outcome no `Verdict` knows (spec §7.3, §13).

`Verdict` is a `StrEnum` and `UnreadVerdict` is a `str`, which is what lets the
dashboard and the postmortem interpolate either and show what the column holds.
It is also why one of them must not be able to hold the other's spelling:
`UnreadVerdict("confirmed")` would compare equal to `Verdict.CONFIRMED` and
fail every `isinstance` narrowing decided against it - read as a verdict where
an outcome is displayed, and absent where one is judged.

Nothing on the read path can make one, since a spelling a verdict has becomes
that verdict. A builder can, which is where this sort of value gets born and is
the whole of the defect `subject` was: a shape production cannot produce, green
in a test. So the type refuses it.
"""

from __future__ import annotations

import pytest
from argus_core.models.action import UnreadVerdict, Verdict
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting

SOME_SPELLING_NO_VERDICT_HAS = "dissolved"
A_SPELLING_A_VERDICT_HAS = Verdict.CONFIRMED.value


@pytest.mark.unit
def test_an_outcome_no_verdict_spells_keeps_the_spelling_it_was_read_with() -> None:
    # The raw text, because every destination that shows an outcome shows this
    # one too. A third state that dropped what it could not read would tell an
    # operator less than the column already holds, and leave an escalation
    # unable to say what stopped it.
    Scenario() \
        .given(
            SOME_SPELLING_NO_VERDICT_HAS
        ) \
        .when(
            lambda: UnreadVerdict(SOME_SPELLING_NO_VERDICT_HAS)
        ) \
        .then(all_of(
            _it_is_spelled(SOME_SPELLING_NO_VERDICT_HAS),
            _it_is_no_verdict()
        ))


@pytest.mark.unit
def test_an_outcome_a_verdict_does_spell_is_refused() -> None:
    Scenario() \
        .given(
            A_SPELLING_A_VERDICT_HAS
        ) \
        .when(
            attempting(lambda: UnreadVerdict(A_SPELLING_A_VERDICT_HAS))
        ) \
        .then(all_of(
            an_error_was_raised(ValueError),
            _it_complains_about(A_SPELLING_A_VERDICT_HAS)
        ))


def _it_is_spelled(spelling: str) -> Assertion[UnreadVerdict]:
    def assertion(outcome: UnreadVerdict) -> bool:
        if outcome != spelling or f"{outcome}" != spelling:
            raise AssertionError(
                f"Expected an outcome spelled [{spelling}], got [{outcome}]."
            )

        return True

    return assertion


def _it_is_no_verdict() -> Assertion[UnreadVerdict]:
    def assertion(outcome: UnreadVerdict) -> bool:
        if isinstance(outcome, Verdict):
            raise AssertionError(
                f"Expected [{outcome}] to be no `Verdict`, and it is [{outcome!r}] - "
                f"so every branch narrowing on one would take it."
            )

        return True

    return assertion


def _it_complains_about(spelling: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if spelling not in str(error):
            raise AssertionError(
                f"Expected the refusal to name [{spelling}], and it said: {error}."
            )

        return True

    return assertion
