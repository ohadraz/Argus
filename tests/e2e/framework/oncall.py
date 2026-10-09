"""The on-call platform as a case plays it: one PagerDuty incident, and what
PagerDuty says when somebody resolves it.

The incident is staged in `pagerduty_double` and linked the way a real one is:
Grafana pages PagerDuty with the alert group's key, PagerDuty stamps that key's
SHA-256 on the alert it raises, and Argus finds the incident by the same digest
of the key Grafana sent it.

The delivery is posted by the case itself, signed as PagerDuty signs it. The
double reads; nothing in the stack plays PagerDuty's webhook, because a real
one needs a public address and a suite has none.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import httpx2
from argus_core import get_settings, to_iso
from oncall_source.pagerduty_webhooks import (
    AGENT,
    DATA,
    EVENT,
    EVENT_TYPE,
    ID,
    RESOLVE_REASON,
    RESOLVED_EVENT,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
    SUMMARY,
    TYPE,
    USER_AGENT,
)
from pagerduty_double.server import DEFAULT_BASE_URL as PAGERDUTY_DOUBLE_BASE_URL

from tests.e2e.framework.argus import ARGUS_WEB_BASE_URL, REQUEST_TIMEOUT_SECONDS


def the_on_call_platform_holds(incident_id: str,
                               paged_for: dict[str, Any],
                               paged_at: datetime,
                               resolved_after: timedelta,
                               acknowledged_after: dict[str, timedelta],
                               titles: dict[str, str] | None = None,
                               resolution_note: str | None = None) -> Callable[[], None]:
    """Stages the PagerDuty incident this alert paged, acknowledged and resolved.

    `acknowledged_after` maps each responder to how long after the page they
    picked it up, and `titles` what any of them is called. `resolution_note` is
    what the person who resolved it wrote, filed as PagerDuty files it.
    """
    titles = titles or {}

    def staged() -> None:
        httpx2.post(
            f"{PAGERDUTY_DOUBLE_BASE_URL}/double-control/incident",
            json={
                "id": incident_id,
                "created_at": to_iso(paged_at),
                "resolved_at": to_iso(paged_at + resolved_after),
                "alert_keys": [_the_key_pagerduty_stamps(paged_for)],
                "acknowledgements": [
                    {
                        "at": to_iso(paged_at + waited),
                        "user_id": responder,
                        "job_title": titles.get(responder)
                    }
                    for responder, waited in acknowledged_after.items()
                ],
                "resolution_note": resolution_note
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            verify=False
        ).raise_for_status()

    return staged


def a_resolution_by(person: str, person_id: str, incident_id: str) -> dict[str, Any]:
    """PagerDuty's `incident.resolved`, as a person resolving it from its page sends it.

    Only what Argus reads, in PagerDuty's own nesting: who acted, as a user
    reference carrying their name, and the incident they acted on. No
    `resolve_reason`, which PagerDuty fills in only for a merge.
    """
    return {
        EVENT: {
            EVENT_TYPE: RESOLVED_EVENT,
            AGENT: {ID: person_id, TYPE: USER_AGENT, SUMMARY: person},
            DATA: {ID: incident_id, TYPE: "incident", RESOLVE_REASON: None}
        }
    }


def the_on_call_platform_delivers(delivery: dict[str, Any]) -> httpx2.Response:
    """Posts one delivery to Argus, signed with the stack's webhook secret."""
    body = json.dumps(delivery).encode()
    secret = get_settings().pagerduty_webhook_secret.encode()
    signature = SIGNATURE_VERSION + hmac.new(secret, body, hashlib.sha256).hexdigest()

    return httpx2.post(
        f"{ARGUS_WEB_BASE_URL}/webhooks/oncall",
        content=body,
        headers={"Content-Type": "application/json", SIGNATURE_HEADER: signature},
        timeout=REQUEST_TIMEOUT_SECONDS
    )


def _the_key_pagerduty_stamps(alert: dict[str, Any]) -> str:
    """The alert key PagerDuty's Grafana integration gives the alert it raises."""
    return hashlib.sha256(alert["groupKey"].encode()).hexdigest()
