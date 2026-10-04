"""The payloads an endpoint is sent, in the shape the sender really uses."""

from __future__ import annotations

from typing import Any

from argus_web.grafana import CLAIM_ANNOTATION


def a_grafana_payload(service: str = "kukibuki",
                      alert_name: str = "HighErrorRate",
                      onset: str | None = None,
                      claim: str | None = None,
                      stale_entry_keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    """One firing alert, nested the way Grafana nests it.

    The whole envelope rather than the fields Argus wants, because the nesting
    is what the parser exists to undo - a fixture already flattened would test
    the parser against its own output.

    `onset` is absent by default, because almost no alert states one: a rule
    that fires on a series is reporting a minute Argus can measure for itself.
    An alert carries one only where the thing that fired it knows something the
    series cannot say - a check reporting what it found long after the writing
    went wrong - which is why it is an annotation of its own rather than
    `startsAt`. Those two differ by a week in the case this exists for.

    `claim` is absent by default for the same reason and with a different
    consequence: a sender that says nothing about what its rule watched is read
    as a threshold rule, which is what the default payload here is. Typed as a
    plain string rather than as `AlarmClaim`, because a value no member spells
    is a case the parser has to answer for and a builder that could only produce
    members could not stage it.
    """
    annotations = {"summary": f"Error rate above threshold on {service}"}

    if onset:
        annotations["onset"] = onset

    if claim is not None:
        annotations[CLAIM_ANNOTATION] = claim

    if stale_entry_keys is not None:
        annotations["stale_entry_keys"] = ",".join(stale_entry_keys)
        annotations["stale_entries_found"] = str(len(stale_entry_keys))

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
                "annotations": annotations,
                "startsAt": "2026-08-14T10:15:00Z",
                "endsAt": "0001-01-01T00:00:00Z"
            }
        ]
    }
