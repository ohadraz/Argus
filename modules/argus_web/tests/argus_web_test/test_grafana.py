from __future__ import annotations

from typing import Any

import pytest
from argus_web.grafana import parse_grafana_alert


@pytest.mark.unit
def test_parse_grafana_alert_maps_labels_to_alert_fields() -> None:
    payload = _a_grafana_payload(service="checkout", alert_name="HighErrorRate")

    alert = parse_grafana_alert(payload)

    assert alert.service == "checkout"
    assert alert.alert_name == "HighErrorRate"
    assert alert.severity == "critical"


@pytest.mark.unit
def test_parse_grafana_alert_does_not_leak_grafana_labels_nesting() -> None:
    payload = _a_grafana_payload()

    alert = parse_grafana_alert(payload)

    assert not hasattr(alert, "labels")


def _a_grafana_payload(service: str = "kukibuki", 
                       alert_name: str = "HighErrorRate") -> dict[str, Any]:
    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": "critical",
                },
                "annotations": {"summary": f"Error rate above threshold on {service}"},
                "startsAt": "2026-08-14T10:15:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ],
    }
