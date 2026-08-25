from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from argus_core.timestamps import to_iso


def a_grafana_style_alert_with(service: str = "some-service",
                                alert_name: str = "some-error-name",
                                severity: str = "some-severity",
                                started_at: datetime | None = None) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` defaults to now, and that default matters: retrieval is
    anchored on the alert time, and the Target Service seeds a scenario
    relative to the moment it was seeded. A hardcoded timestamp puts the
    metrics window somewhere the fixture's minutes are not, so Argus
    retrieves nothing and honestly reports that it found nothing - a green
    test turning red for a reason that has nothing to do with Argus.
    """
    summary = f"Error rate above threshold on {service}"
    alert_time = started_at if started_at is not None else datetime.now(UTC)

    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": severity,
                },
                "annotations": {
                    "summary": summary,
                },
                "startsAt": to_iso(alert_time),
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"http://grafana.local/alerting/grafana/{service}/view",
                "fingerprint": "abc123def456",
            }
        ],
        "groupLabels": {"alertname": alert_name},
        "commonLabels": {"alertname": alert_name, "service": service},
        "commonAnnotations": {"summary": summary},
        "externalURL": "http://grafana.local",
        "version": "1",
        "groupKey": f'{{}}/{{alertname="{alert_name}"}}',
    }
