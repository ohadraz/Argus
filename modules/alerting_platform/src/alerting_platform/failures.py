"""How the alerting platform says it could not answer."""

from __future__ import annotations


class AlertRuleUnreadable(Exception):
    """The platform would not say where the rule stands.

    Raised rather than answered as normal, because "normal" is the answer that
    confirms whatever was just done.
    """
