from __future__ import annotations

from datetime import datetime
from typing import Any

from argus_core import to_iso

# The words the shop's own monitoring pages with wherever its other rules do not
# fire: its error-rate rule's summary (`_BY_DEFAULT` in the demo app's
# `monitoring.py`). A case whose scenario trips another rule passes that rule's
# words, as its alert name names that rule.
THE_ERROR_RATE_RULES_WORDS = "Error rate above threshold for 5m"

# The uid of the rule those words are the summary of (`HIGH_ERROR_RATE` in the
# demo app's `alert_rules.py`), which an alert links where no scenario is staged.
# Grafana's webhook names the rule that fired only in its link, so a link naming
# no rule the shop has is an alert no real Grafana sends - and one whose rule
# Argus asks for and is told does not exist.
THE_ERROR_RATE_RULE = "io-shop-high-error-rate"


def a_grafana_style_alert_with(service: str = "some-service",
                                alert_name: str = "some-error-name",
                                severity: str = "some-severity",
                                started_at: datetime | None = None,
                                summary: str = THE_ERROR_RATE_RULES_WORDS) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` is left to whoever sends it, which stamps it with the moment it
    is sent, unless `started_at` is given. That default matters twice over:
    retrieval is anchored on the alert time, and the Target Service seeds a
    scenario relative to the moment it was seeded. A hardcoded timestamp puts
    the metrics window somewhere the fixture's minutes are not, so Argus
    retrieves nothing and honestly reports that it found nothing - a green
    test turning red for a reason that has nothing to do with Argus. And a
    stamp taken here is taken before the case seeds, by however long the seed
    waited, which can put the alert before the rule could have fired.

    `summary` is the words the alert was sent with, which Argus reads as the
    sender's own account of what it measured and names the paging rule's
    series by. Three latency rules share one alert name, so the words are the
    only thing in the page that says which percentile moved.

    The link names the error-rate rule, whose words the summary is by default.
    Where a scenario is staged, sending the alert links its own rule instead.
    """
    starts_at = {"startsAt": to_iso(started_at)} if started_at is not None else {}

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
                **starts_at,
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"http://grafana.local/alerting/grafana/{THE_ERROR_RATE_RULE}/view",
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
