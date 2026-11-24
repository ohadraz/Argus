"""What Argus does with a delivery from the on-call platform.

One thing, and for one kind of delivery: a person resolved the platform's
incident, so Argus resolves its own - credited to that person, through that
platform, with what they wrote (spec §16: a person saying it is over is fact).
Everything else the platform says is noted and left alone. Which deliveries are
a person's resolution is the platform adapter's to say, because only it can tell
a person from an integration; which incidents the page is about is the incident
record's to say (`incidents_a_page_is_about`), because it is a decision about
incidents; this module carries the delivery to it and the answer back.

Nothing here knows which platform answered. It holds the port.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from core.models import ON_CALL_INCIDENT, Lifespan, Reference, Report, ReportChannel
from incident_record import PersonsEnding
from oncall_source.platform import (
    Merged,
    OnCallPlatform,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)

logger = logging.getLogger(__name__)


class IncidentRecord(Protocol):
    """The incident record, for what a platform's resolution asks of it.

    A seam rather than the incident record's roles and decisions themselves,
    because those are asserted in its own suite. What belongs here is which
    deliveries reach them, and with what.
    """

    def incidents_a_page_is_about(self,
                                  page: str,
                                  keys: Sequence[str],
                                  the_pages_life: Callable[[], Lifespan]) -> list[str]:
        """The Argus incidents the platform's page is about, each once."""
        ...

    def know_it_as(self, incident_id: str, reference: Reference) -> None:
        """Gives the incident one more name."""
        ...

    def resolve(self, incident_id: str, reported: Report) -> PersonsEnding:
        """Resolves the incident as a person reported it."""
        ...


def receive_delivery(body: bytes,
                     headers: Mapping[str, str],
                     *,
                     platform: OnCallPlatform,
                     record: IncidentRecord) -> None:
    """Acts on one delivery from the on-call platform, if it is a person's
    resolution of an incident Argus has.

    Raises `OnCallDeliveryUnverified` for a delivery the platform did not sign,
    and `OnCallUnavailable` when the platform cannot be read while matching - the
    second deliberately, so the delivery is answered as a failure and sent
    again rather than lost. Every other outcome returns: a delivery about
    something Argus does not act on was still received.
    """
    delivery = platform.parse_delivery(body, headers)

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
    """Resolves every Argus incident a person's resolution is about, if any.

    The page's keys are read whether or not anything holds them; when it was
    open is read only if the record asks, which it does only where an incident
    holds one of the keys.
    """
    def the_pages_life() -> Lifespan:
        reported = platform.reported_incident(platform_incident)

        return Lifespan(began_at=reported.began_at, ended_at=reported.ended_at)

    about = record.incidents_a_page_is_about(platform_incident,
                                             platform.keys_of(platform_incident),
                                             the_pages_life)

    if not about:
        # The webhook covers every incident on the services it watches, and
        # Argus opened only some of them.
        logger.info("on-call resolution matched no incident", extra={
            "platform_incident": platform_incident
        })
        return

    reported = Report(
        by=by,
        channel=ReportChannel.ON_CALL_PLATFORM,
        platform=platform.name,
        note=platform.resolution_note(platform_incident)
    )

    # Each is resolved on its own, and refuses on its own: one of them may have
    # ended in a way a resolution would contradict.
    for incident_id in about:
        record.know_it_as(incident_id, Reference(
            source=platform.name, kind=ON_CALL_INCIDENT, value=platform_incident
        ))
        record.resolve(incident_id, reported)
