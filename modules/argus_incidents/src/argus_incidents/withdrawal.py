"""How an incident is taken back - and nothing about how one is walked.

The Orchestrator's second entrypoint, beside `intake`, and in this package for
its reason rather than for tidiness: `argus_web` calls this, and anything
`argus_web` can import must reach nothing that walks a graph.

Marking is all this does. The walk that is running the incident finds out by
reading the status back, and unwinds what it had done itself - which is what
keeps one writer on an incident. A withdrawal that undid actions from here would
be a second writer racing the first for the same rows.
"""

from __future__ import annotations

import logging

from argus_core import Connections
from argus_core.events import Publisher, StatusChanged, publish
from argus_core.models import IncidentStatus, Report

from argus_incidents.repository import incidents

logger = logging.getLogger(__name__)


def withdraw_incident(incident_id: str,
                      reported: Report,
                      connections: Connections,
                      publisher: Publisher) -> bool:
    """Stops Argus working on an incident, and says whether it took effect.

    `reported` is who withdrew it and through which door. It travels on the
    change itself, as a resolution's does: the account is what every reader of
    the incident reads, and the person is the one part of this ending Argus
    cannot derive.

    The publishing is what a page watching the incident finds out from. A
    withdrawal that only wrote the row would leave that page polling an
    incident that had already ended - and published only where the row actually
    moved, so a second press does not tell every watcher the incident ended
    twice.
    """
    with connections() as conn:
        withdrawn = incidents.withdraw(conn, incident_id)

    if withdrawn:
        # The channel and not the name, as for a resolution: which door it came
        # through is what an operator reading the log needs.
        logger.info("incident withdrawn", extra={"channel": reported.channel})
        publish(
            StatusChanged(
                incident_id=incident_id,
                to_status=IncidentStatus.WITHDRAWN,
                reported=reported
            ),
            publisher
        )

    return withdrawn
