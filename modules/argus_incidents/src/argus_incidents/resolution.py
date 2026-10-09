"""How a person tells Argus the incident is over - and nothing about how one is
walked.

The withdrawal's sibling, and in this package for its reason: `argus_web` calls
this, and anything `argus_web` can import must reach nothing that walks a graph.

Marking is all this does, as it is all the withdrawal does. The walk that is
running the incident finds out by reading the status back, and stops where it
is - but where a withdrawal sends it straight out and has its changes put back,
a resolution sends it on to remember what was tried and write the incident up,
and puts nothing back. The person who reported it over has the world as it is,
and a change undone behind them would be Argus second-guessing the one report
it does not test (spec §16).
"""

from __future__ import annotations

import logging

from argus_core import Connections
from argus_core.events import Publisher, StatusChanged, publish
from argus_core.models import IncidentStatus, Report

from argus_incidents.repository import incidents

logger = logging.getLogger(__name__)


def resolve_incident(incident_id: str,
                     reported: Report,
                     connections: Connections,
                     publisher: Publisher) -> bool:
    """Records that a person reported the incident resolved, and says whether
    it took effect.

    The report is published with the change rather than kept anywhere else,
    because the account is what every reader of the incident reads - the page,
    the Slack thread, the postmortem - and the person is the one part of this
    ending Argus cannot derive.

    Published only where the row actually moved, so a second press, or a press
    on an incident somebody withdrew meanwhile, says nothing untrue to anybody
    watching.
    """
    with connections() as conn:
        resolved = incidents.resolve(conn, incident_id)

    if resolved:
        # The channel and not the name: which door the report came through is
        # what an operator reading the log needs, and the name is in the
        # account for anybody who needs that.
        logger.info("incident resolved", extra={"channel": reported.channel})
        publish(
            StatusChanged(
                incident_id=incident_id,
                to_status=IncidentStatus.RESOLVED,
                reported=reported
            ),
            publisher
        )

    return resolved
