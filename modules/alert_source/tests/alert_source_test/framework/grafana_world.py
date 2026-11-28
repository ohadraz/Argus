"""What was sent, written as Grafana sends it.

The port's suite runs the Grafana adapter over these bytes, beside the double
over its own writing of the same thing. One writer of Grafana's envelope serves
both suites: this maps what was sent onto `a_grafana_payload`, which the wire
suite builds from, so the two cannot spell a notification differently.

How an alert is written: one alert in its envelope, each field the alert sets
where the adapter reads it - its rule in a link of the shape Grafana's releases
build - and none it leaves unset. The claim is written only where it is not the
one a silence means, so an alert that says nothing about its rule is sent
saying nothing. A delivery of resolutions alone is one resolved alert.

A seed this writer cannot say is refused rather than written: references (a
group key's hash and each firing are Grafana's own names, read off fields no
`Reference` says how to fill), and stale keys without their count or a count
without its keys (`a_grafana_payload` writes the count from the keys, so it
says both or neither).
"""

from __future__ import annotations

import json

from alert_source import OnlyResolved
from alert_source.grafana import RESOLVED
from alert_source_double import Sent
from core import to_iso
from core.models import AlarmClaim

from alert_source_test.framework.builders import a_grafana_payload


def as_grafana_sends(sent: Sent) -> bytes:
    """`sent`, as Grafana's webhook delivers it."""
    if isinstance(sent, OnlyResolved):
        return json.dumps(a_grafana_payload(status=RESOLVED)).encode()

    if sent.references:
        raise ValueError(f"the alert names references {sent.references}: Grafana's own "
                         f"names are read off fields no reference says how to write")

    if (sent.stale_entry_keys is None) != (sent.stale_entries_found is None):
        raise ValueError("stale keys and their count are written together: the builder "
                         "writes the count from the keys")

    return json.dumps(a_grafana_payload(
        service=sent.service,
        alert_name=sent.alert_name,
        severity=sent.severity,
        summary=sent.summary,
        starts_at=to_iso(sent.started_at) if sent.started_at is not None else None,
        onset=to_iso(sent.stated_onset) if sent.stated_onset is not None else None,
        claim=None if sent.claim is AlarmClaim.A_SERIES_CONDITION else sent.claim,
        stale_entry_keys=sent.stale_entry_keys,
        rule_uid=sent.rule
    )).encode()
