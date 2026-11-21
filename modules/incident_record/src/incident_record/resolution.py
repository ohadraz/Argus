"""How a person tells Argus the incident is over - and nothing about how one is
walked.

The withdrawal's sibling, and in this package for its reason: `web_app` calls
this, and anything `web_app` can import must reach nothing that walks a graph.

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

from core import Connections, unit_of_work
from core.events import StatusChanged
from core.models import IncidentStatus, Report

from incident_record.publishing import PublisherFor, publish_beside
from incident_record.repository import incidents, taken_actions
from incident_record.repository.taken_actions import NoLongerOpen

logger = logging.getLogger(__name__)


def resolve_incident(incident_id: str,
                     reported: Report,
                     connections: Connections,
                     publisher_for: PublisherFor) -> bool:
    """Records that a person reported the incident resolved, and says whether
    it took effect.

    The report is published with the change rather than kept anywhere else,
    because the account is what every reader of the incident reads - the page,
    the Slack thread, the postmortem - and the person is the one part of this
    ending Argus cannot derive.

    Published only where the row actually moved, so a second press, or a press
    on an incident somebody withdrew meanwhile, says nothing untrue to anybody
    watching.

    The change is built before the row is written, so a row ending now ends at
    the moment the account says it did.

    Every change the incident made stops being open on its subject in the same
    write (spec §11.1): Argus never puts back a resolved incident's changes,
    so nothing of its could undo another incident's, and what it left standing
    is the person's now. Another incident may then act on those subjects.

    The account is written beside the change, on its connection and inside its
    transaction: the two commit together, so no crash leaves an incident
    resolved that no reader is told of. And beside it rather than within it - in
    a savepoint of its own - so an account that cannot be written fails alone,
    and the person's resolution stands.
    """
    narrating = StatusChanged(incident_id=incident_id,
                              to_status=IncidentStatus.RESOLVED,
                              reported=reported)

    with unit_of_work(connections) as conn:
        resolved = incidents.resolve(conn, incident_id, at=narrating.at)

        if resolved:
            taken_actions.no_longer_open(conn, incident_id, narrating.at,
                                         which=NoLongerOpen.EVERY_ROW)
            publish_beside(conn, narrating, publisher_for(conn))

    if resolved:
        # The channel and not the name: which door the report came through is
        # what an operator reading the log needs, and the name is in the
        # account for anybody who needs that.
        logger.info("incident resolved", extra={"channel": reported.channel})

    return resolved
