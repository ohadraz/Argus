from __future__ import annotations

from argus_core.db import Connections
from argus_core.events import Publisher
from argus_core.models.alert import Alert

from argus_incidents.publishing import acknowledge_alert
from argus_incidents.repository import incidents, runs

"""How an incident starts - and nothing about how one is walked.

Here rather than in `orchestrator` so that the process receiving alerts cannot
invoke the graph even by accident. `orchestrator.entrypoint` builds the
compiled graph at import time's first call and pulls the whole of langgraph in
with it; anything importing it can run an incident, and a web process that can
run an incident eventually does.

The split is therefore the point rather than tidiness, and it is now a package
boundary rather than a convention: `argus_web` depends on this package and not
on `orchestrator`, so langgraph is never installed in the web process at all.
What walks is the worker's, in its own process.
"""


def start_incident(alert: Alert,
                   connections: Connections,
                   publisher: Publisher) -> str:
    """The Orchestrator's entrypoint (spec §7.1): creates the `Incident` row
    and puts its walk in line, called by `argus_web` (§7.9) with a normalized
    `Alert` domain object - never a vendor's raw payload.

    Returns as soon as the incident exists. An investigation that ran inside
    the request would hold the caller's connection - and one worker of a web
    server - for its whole length, and would be abandoned mid-walk the moment
    that connection timed out.

    Both collaborators are given rather than reached for: what a web process
    holds - a pool, a subscriber writing into it - is that process's to decide,
    and a function that helped itself to either would be one no caller could
    stand in for.
    """
    with connections() as conn:
        incident_id = incidents.create(conn, alert)

    # The story's first line, published from here because by the time a node
    # runs the alert has already been received - and published after the row
    # exists, so there is an incident for it to belong to.
    acknowledge_alert(incident_id, alert, publisher)

    with connections() as conn:
        runs.enqueue(conn, incident_id)

    return incident_id
