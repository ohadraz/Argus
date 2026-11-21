"""The alerting platform, as the read tier asks it about a rule.

Named for the role - whatever evaluates the rules that page - and answered by
one adapter named for the vendor. What crosses is Argus's own values: a rule's
evaluation and the series it watches, never a route, a field or a unit id.

What the series measures is not asked here. The series is a query in the
metrics source's language, and only the metrics source's adapter reads one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from core.models import RuleSeries, Unit
from pydantic import BaseModel, ConfigDict, Field


class RuleEvaluation(BaseModel):
    """Where an alert rule stands and how it reads its service, as the platform
    evaluating it keeps them: the platform's part of `AlertRuleStanding`.

    `is_normal`, `evaluated_at` and the four durations mean what they mean on
    the standing. `series` is the one series the rule's condition is evaluated
    over, and `None` where no one series could be followed to. `series_unit` is
    the unit the platform shows that series in, and `None` where it shows none
    Argus can say - not that the series has no unit, which is the metrics
    source's to say next.
    """

    model_config = ConfigDict(frozen=True)

    rule: str
    is_normal: bool
    evaluated_at: datetime
    range_seconds: int = Field(ge=0)
    interval_seconds: int = Field(ge=0)
    keep_firing_for_seconds: int = Field(ge=0)
    pending_seconds: int = Field(ge=0)
    series: RuleSeries | None = None
    series_unit: Unit | None = None


class AlertingPlatform(Protocol):
    """The platform that evaluates the rules that page, for the two questions
    the read tier asks it."""

    def evaluation_of(self, rule: str, /) -> RuleEvaluation:
        """Where `rule` stands now, and how it reads its service.

        Raises `AlertRuleUnreadable` rather than answering normal, because
        "normal" is the answer that confirms whatever was just done.
        """
        ...

    def series_of(self, rule: str, /) -> RuleSeries | None:
        """The series `rule` is evaluated over and which way it is worse, or
        `None` where that cannot be said for certain - the platform not
        answering included: the series is a sixth signal a window can do
        without."""
        ...
