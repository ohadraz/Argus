from __future__ import annotations

from argus_core.models.action import Outcome, Verdict
from argus_testkit.assertions import Assertion


def the_verdict_is(verdict: Verdict) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.verdict is not verdict:
            raise AssertionError(
                f"Expected a verdict of [{verdict}], got [{outcome.verdict}]."
            )

        return True

    return assertion
