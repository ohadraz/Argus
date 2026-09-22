"""The payloads an endpoint is sent, in the shape the sender really uses."""

from __future__ import annotations

from typing import Any


def a_grafana_payload(service: str = "kukibuki",
                      alert_name: str = "HighErrorRate") -> dict[str, Any]:
    """One firing alert, nested the way Grafana nests it.

    The whole envelope rather than the fields Argus wants, because the nesting
    is what the parser exists to undo - a fixture already flattened would test
    the parser against its own output.
    """
    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": "critical"
                },
                "annotations": {"summary": f"Error rate above threshold on {service}"},
                "startsAt": "2026-08-14T10:15:00Z",
                "endsAt": "0001-01-01T00:00:00Z"
            }
        ]
    }
