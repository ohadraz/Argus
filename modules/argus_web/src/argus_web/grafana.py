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
        # An annotation rather than a label, because Grafana's labels are the
        # alert's identity and a timestamp in one would make every firing a
        # different alert. Absent from almost every payload, and left unset
        # rather than defaulted to `startsAt`: an onset invented here would be
        # a measured minute's rival carrying none of its evidence, and would
        # be the minute somebody noticed rather than the minute it began.
        stated_onset=annotations.get("onset"),
    )
