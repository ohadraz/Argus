from __future__ import annotations

from typing import Any

from argus_core.models import Alert


def parse_grafana_alert(raw_payload: dict[str, Any]) -> Alert:
    """Deterministic parser for Grafana's unified-alerting webhook format -
    plain field mapping, no LLM call (design.md Non-Goals; spec §7.9/§25
    tracks generic/LLM-based ingestion as separate future work)."""
    alert = raw_payload["alerts"][0]
    labels = alert["labels"]
    annotations = alert.get("annotations", {})
    return Alert(
        service=labels["service"],
        alert_name=labels["alertname"],
        severity=labels.get("severity"),
        summary=annotations.get("summary"),
        started_at=alert.get("startsAt"),
    )
