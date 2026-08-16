from typing import Any


def a_grafana_style_alert_with(service: str = "some-service",
                                alert_name: str = "some-error-name",
                                severity: str = "some-severity") -> dict[str, Any]:
    summary = f"Error rate above threshold on {service}"

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
                "startsAt": "2026-08-14T10:15:00Z",
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