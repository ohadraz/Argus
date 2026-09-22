from __future__ import annotations

from agent_mitigation import Action
from argus_core.models import Outcome, Verdict
from argus_testkit.assertions import Assertion


def the_verdict_is(verdict: Verdict) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.verdict is not verdict:
            raise AssertionError(
                f"Expected a verdict of [{verdict}], got [{outcome.verdict}]."
            )

        return True

    return assertion


def nothing_was_proposed() -> Assertion[Action | None]:
    """That the agent found nothing worth doing, rather than something wrong.

    `None` is a real answer here and not an absence of one: a hypothesis this
    tier has no action for is a hypothesis it declines, and the walk escalates
    on that rather than treating it as a failure to decide.
    """
    def assertion(action: Action | None) -> bool:
        if action is not None:
            raise AssertionError(f"Expected no action to be proposed, got [{action}].")

        return True

    return assertion
