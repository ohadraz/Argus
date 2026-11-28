"""The alerting platform's port, answered from memory.

Built from an `AlertingState`, and changed by nothing: the port only reads.
Everything it says is what the port promises and the port's suite pins over
both adapters - so it refuses an evaluation it cannot vouch for rather than
answering normal, answers no series rather than refusing, and says a unit only
beside the series it is the unit of.
"""

from __future__ import annotations

from alerting_platform import AlertRuleUnreadable, RuleEvaluation
from core.models import RuleSeries

from alerting_platform_double.state import AlertingState


class InMemoryAlertingPlatform:
    """An alerting platform held in memory.

    `unreachable` builds a platform nothing reaches: every evaluation is
    refused, and every series is none.
    """

    def __init__(self, state: AlertingState, *, unreachable: bool = False) -> None:
        self._rules = {held.evaluation.rule: held for held in state.rules}
        self._unreachable = unreachable

    def evaluation_of(self, rule: str, /) -> RuleEvaluation:
        """Refused for a platform nothing reaches, a rule it does not evaluate,
        and an evaluation that measured nothing - never answered as normal."""
        if self._unreachable:
            raise AlertRuleUnreadable("the platform is not reachable")

        held = self._rules.get(rule)

        if held is None:
            raise AlertRuleUnreadable(f"the platform evaluates no rule [{rule}]")

        if not held.measured:
            raise AlertRuleUnreadable(f"rule [{rule}]'s last evaluation measured nothing")

        if held.evaluation.series is None:
            return held.evaluation.model_copy(update={"series_unit": None})

        return held.evaluation

    def series_of(self, rule: str, /) -> RuleSeries | None:
        """`None` for a platform nothing reaches and a rule it does not
        evaluate: the series is a signal a window can do without."""
        if self._unreachable:
            return None

        held = self._rules.get(rule)

        return held.evaluation.series if held is not None else None
