"""Where the alert rule that paged stands."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AlertRuleStanding(BaseModel):
    """Whether an alert rule has stopped firing, as of an evaluation that can be
    dated, and how the rule reads its service.

    A contract rather than one module's value, because the parties naming it
    span modules: the read tier reads it off whatever evaluates the rules, the
    read client carries it across the wire, Mitigation judges an action on a
    series alert by it, and the postmortem reads how long the rule waits. It
    names no vendor - the rule's identity is whatever the alert carried, and
    which monitoring stack answers for it is the read tier's to know.

    `is_normal` is the rule having stopped firing, and nothing short of that: a
    rule whose condition holds but has not yet held long enough to fire is not
    normal. `evaluated_at` is when the answer was true, because an evaluation
    that came before an action says nothing about the action.

    The four durations are how the rule reads its service. Three of them say
    how long a recovery takes to show in it: the rule looks back over
    `range_seconds`, is evaluated every `interval_seconds`, and goes on firing for
    `keep_firing_for_seconds` after its condition stops holding. A rule that is
    a check rather than a query over a range looks back over nothing. The fourth,
    `pending_seconds`, is how long its condition has to hold before it fires -
    part of the time from an onset to its alert, and none at all for a rule that
    fires as soon as its condition holds.
    """

    rule: str
    is_normal: bool
    evaluated_at: datetime
    range_seconds: int = Field(ge=0)
    interval_seconds: int = Field(ge=0)
    keep_firing_for_seconds: int = Field(ge=0)
    pending_seconds: int = Field(ge=0)
