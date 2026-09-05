from __future__ import annotations

from argus_core.db import connect
from argus_core.models.alert import Alert

from orchestrator.publishing import acknowledge_alert
from orchestrator.repository import incidents, runs

"""How an incident starts - and nothing about how one is walked.

A module of its own so that the process receiving alerts cannot invoke the
graph even by accident. `orchestrator.entrypoint` builds the compiled graph at
import time's first call and pulls the whole of langgraph in with it; anything
importing it can run an incident, and a web process that can run an incident
eventually does.

The split is therefore the point rather than tidiness: `argus_web` imports this
and reaches nothing that walks. What walks is the worker's, in its own process.
"""


def start_incident(alert: Alert) -> str:
    """The Orchestrator's entrypoint (spec §7.1): creates the `Incident` row
    and puts its walk in line, called by `argus_web` (§7.9) with a normalized
    `Alert` domain object - never a vendor's raw payload.

    Returns as soon as the incident exists. An investigation that ran inside
    the request would hold the caller's connection - and one worker of a web
    server - for its whole length, and would be abandoned mid-walk the moment
    that connection timed out.
    """
    with connect() as conn:
        incident_id = incidents.create(conn, alert)

    # The story's first line, published from here because by the time a node
    # runs the alert has already been received - and published after the row
    # exists, so there is an incident for it to belong to.
    acknowledge_alert(incident_id, alert)

    with connect() as conn:
        runs.enqueue(conn, incident_id)

    return incident_id
