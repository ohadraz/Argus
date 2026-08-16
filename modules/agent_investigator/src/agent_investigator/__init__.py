from __future__ import annotations

from argus_core.models import Alert

STUB_CONFIDENCE = 0.9


def investigate(alert: Alert) -> tuple[str, float]:
    """Stub investigation (spec §7.2, §9) - no ReAct loop, no tool calls
    (design.md Non-Goals). Always returns a fixed hypothesis at a confidence
    above §10's 0.75 mitigate threshold."""
    hypothesis = (
        f"stub hypothesis: {alert.alert_name} on {alert.service} "
        "correlates with a recent change"
    )
    return hypothesis, STUB_CONFIDENCE
