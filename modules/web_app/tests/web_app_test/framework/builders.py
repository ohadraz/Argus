"""The payloads an endpoint is sent, in the shape the sender really uses."""

from __future__ import annotations

from typing import Any


def a_grafana_payload(service: str = "kukibuki",
                      rule_uid: str | None = None,
                      status: str = "firing") -> dict[str, Any]:
    """One alert, firing unless `status` says otherwise, nested the way Grafana
    nests it - what the alert routes are sent by the deployment's first sender.

    Only what an endpoint's cases vary: the service it is about, the rule that
    fired, in the link to it where Grafana says it, and whether it is firing.
    Everything else a notification can carry is the Grafana adapter's to read,
    and staged by that adapter's own suite.
    """
    alert: dict[str, Any] = {
        "status": status,
        "labels": {
            "alertname": "HighErrorRate",
            "service": service,
            "severity": "critical"
        },
        "annotations": {"summary": f"Error rate above threshold on {service}"},
        "startsAt": "2026-08-14T10:15:00Z",
        "endsAt": "0001-01-01T00:00:00Z"
    }

    if rule_uid is not None:
        alert["generatorURL"] = f"http://grafana.test/alerting/grafana/{rule_uid}/view?orgId=1"

    return {
        "receiver": "argus-webhook",
        "status": status,
        "alerts": [alert]
    }
