"""The alerting platform, as Argus needs it (spec §7.3, §12).

A port and the one adapter behind it. The port is named for the role - what the
read tier asks of whatever evaluates the rules that page - and the adapter for
the vendor that answers today, in `alerting_platform.grafana`. Nothing above the
port sees a route, a field of a rule's definition or a unit id.

The adapter is not exported here. It is built where the read server is wired,
and everything else is handed it typed as the port.
"""

from __future__ import annotations

from alerting_platform.failures import AlertRuleUnreadable
from alerting_platform.port import AlertingPlatform, RuleEvaluation

__all__ = [
    "AlertRuleUnreadable",
    "AlertingPlatform",
    "RuleEvaluation"
]
