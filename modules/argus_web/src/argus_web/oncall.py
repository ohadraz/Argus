"""What Argus does with a delivery from the on-call platform.

One thing, and for one kind of delivery: a person resolved the platform's
incident, so Argus resolves its own - credited to that person, through that
platform, with what they wrote (spec §16: a person saying it is over is fact).
Everything else the platform says is noted and left alone. Which deliveries are
a person's resolution is the platform adapter's to say, because only it can tell
a person from an integration; this module is about finding the incident.

The incident is found when the resolution arrives, not when the alert did.
Grafana pages the platform and Argus at the same moment, so at intake the
platform's incident may not exist yet; by the time somebody resolves it, it
does. It is found through the keys its senders stamped on it - which a merge
carries over to the incident merged into - or, where an earlier match already
linked it, by the platform's own id.

Nothing here knows which platform answered. It holds the port.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from argus_core import SettingsSlice
from argus_core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    Reference,
    Report,
)
from oncall_source.platform import (
    Merged,
    OnCallPlatform,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)

logger = logging.getLogger(__name__)


class OnCallDeliverySettings(SettingsSlice):
    """What only the process receiving the platform's deliveries may know: the
    secret they are signed with.

    Apart from the reading credential because the worker reads the platform and
    never hears from it, and a process that cannot be told anything has no use
    for the secret that proves who is telling.
    """

    pagerduty_webhook_secret: str


class IncidentRecord(Protocol):
    """The incident record, for what a platform's resolution asks of it.

    A seam rather than the repository and `resolve_incident` themselves,
    because their rows are asserted against a real database in their own
    suite. What belongs here is which deliveries reach them, and with what.
    """

    def incident_known_as(self, kind: str, values: Sequence[str]) -> str | None:
        """The incident holding any of these names of this kind, or `None`."""
        ...

    def know_it_as(self, incident_id: str, reference: Reference) -> None:
        """Gives the incident one more name."""
        ...

    def resolve(self, incident_id: str, reported: Report) -> bool:
        """Resolves the incident as a person reported it; whether it moved."""
        ...


def receive_delivery(body: bytes,
                     headers: Mapping[str, str],
                     *,
                     platform: OnCallPlatform,
                     record: IncidentRecord) -> None:
    """Acts on one delivery from the on-call platform, if it is a person's
    resolution of an incident Argus has.

    Raises `DeliveryUnverified` for a delivery the platform did not sign, and
    `OnCallUnavailable` when the platform cannot be read while matching - the
    second deliberately, so the delivery is answered as a failure and sent
    again rather than lost. Every other outcome returns: a delivery about
    something Argus does not act on was still received.
    """
    delivery = platform.read_delivery(body, headers)

    match delivery:
        case ResolvedByAPerson(platform_incident=platform_incident, by=by):
            _resolve(platform_incident, by, platform, record)
        case ResolvedWithoutAPerson(platform_incident=platform_incident):
            # The monitor's integration clearing its alert, or nobody named at
            # all. Neither is anybody deciding the incident is over, and
            # recovery is Argus's to read from the metrics.
            logger.info("on-call resolution not by a person", extra={
                "platform_incident": platform_incident,
                "resolved_by": delivery.resolved_by
            })
        case Merged(platform_incident=platform_incident, into=into):
            # The incident moved rather than ended. Its alerts went with it,
            # so a person resolving `into` is matched through them.
            logger.info("on-call incident merged", extra={
                "platform_incident": platform_incident, "into": into
            })
        case Reopened(platform_incident=platform_incident):
            # A person's resolution is fact once recorded, and a reopen in the
            # platform does not unsay it.
            logger.info("on-call incident reopened", extra={
                "platform_incident": platform_incident
            })
        case _:
            pass


def _resolve(platform_incident: str,
             by: str,
             platform: OnCallPlatform,
             record: IncidentRecord) -> None:
    """Resolves the Argus incident a person's resolution is about, if any."""
    incident_id = (
        record.incident_known_as(ON_CALL_INCIDENT, [platform_incident])
        or record.incident_known_as(NOTIFICATION_KEY, platform.keys_of(platform_incident))
    )

    if incident_id is None:
        # The webhook covers every incident on the services it watches, and
        # Argus opened only some of them.
        logger.info("on-call resolution matched no incident", extra={
            "platform_incident": platform_incident
        })
        return

    record.know_it_as(incident_id, Reference(
        source=platform.channel, kind=ON_CALL_INCIDENT, value=platform_incident
    ))
    record.resolve(incident_id, Report(
        by=by, channel=platform.channel, note=platform.resolution_note(platform_incident)
    ))
