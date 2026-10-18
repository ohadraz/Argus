from __future__ import annotations

from datetime import datetime
from typing import Any

from argus_core import to_iso, utc_now

# The words the shop's own monitoring pages with wherever its other rules do not
# fire: its error-rate rule's summary (`_BY_DEFAULT` in the demo app's
# `monitoring.py`). A case whose scenario trips another rule passes that rule's
# words, as its alert name names that rule.
THE_ERROR_RATE_RULES_WORDS = "Error rate above threshold for 5m"


def a_grafana_style_alert_with(service: str = "some-service",
                                alert_name: str = "some-error-name",
                                severity: str = "some-severity",
                                started_at: datetime | None = None,
                                summary: str = THE_ERROR_RATE_RULES_WORDS) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` defaults to now, and that default matters: retrieval is
    anchored on the alert time, and the Target Service seeds a scenario
    relative to the moment it was seeded. A hardcoded timestamp puts the
    metrics window somewhere the fixture's minutes are not, so Argus
    retrieves nothing and honestly reports that it found nothing - a green
    test turning red for a reason that has nothing to do with Argus.

    `summary` is the words the alert was sent with, which Argus reads as the
    sender's own account of what it measured and names the paging rule's
    series by. Three latency rules share one alert name, so the words are the
    only thing in the page that says which percentile moved.
    """
    alert_time = started_at if started_at is not None else utc_now()

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
