"""The deliveries an endpoint is sent, in the shape the suite's senders read."""

from __future__ import annotations

from typing import Any

from core.models import Alert

from web_app_test.framework.senders import ONLY_RESOLVED


def an_alert_delivery(service: str = "kukibuki",
                      rule: str | None = None,
                      resolved: bool = False) -> dict[str, Any]:
    """One alert about `service`, as the suite's stand-in sender is sent it - or,
    where `resolved`, a delivery saying only that its rule stopped firing.

    Only what an endpoint's cases vary: the service the alert is about, the
    rule that fired - which a refiring joins its incident by - and whether it
    is firing. What a real sender's notification carries is its
    adapter's to read, and staged by that adapter's own suite.
    """
    if resolved:
        return {ONLY_RESOLVED: True}

    return Alert(service=service,
                 alert_name="HighErrorRate",
                 severity="critical",
                 summary=f"Error rate above threshold on {service}",
                 rule=rule).model_dump(mode="json")
