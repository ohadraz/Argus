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

from __future__ import annotations

import logging
from collections.abc import Mapping

from argus_core import Connections
from argus_core.models import Alert
from argus_core.telemetry import ARGUS_INCIDENT_ID

from argus_incidents.publishing import PublisherFor, acknowledge_alert
from argus_incidents.repository import incidents, runs

logger = logging.getLogger(__name__)


def start_incident(alert: Alert,
                   connections: Connections,
                   publisher_for: PublisherFor,
                   trace_context: Mapping[str, str] = incidents.NO_TRACE_CONTEXT) -> str:
    """The Orchestrator's entrypoint (spec §7.1): creates the `Incident` row
    and puts its walk in line - or, for a rule whose incident is still open,
    answers with that incident - called by `argus_web` (§7.9) with a normalized
    `Alert` domain object - never a vendor's raw payload.

    Returns as soon as the incident exists. An investigation that ran inside
    the request would hold the caller's connection - and one worker of a web
    server - for its whole length, and would be abandoned mid-walk the moment
    that connection timed out.

    Both collaborators are given rather than reached for: what a web process
    holds - a pool, a subscriber writing into it - is that process's to decide,
    and a function that helped itself to either would be one no caller could
    stand in for.

    `trace_context` is the trace the alert arrived in, kept with a new
    incident so that every walk of it continues that trace. An alert joining
    an open incident keeps nothing: the incident's trace is the first alert's.

    Its lines name the incident themselves, under the key a walk's lines are
    stamped with: nothing is walking it yet, so there is no baggage to stamp
    them from.
    """
    # A rule that fired again for a service while its incident there is still
    # going on is that incident, not a second one. An alert naming no rule has
    # nothing to be joined by.
    if alert.rule is not None:
        with connections() as conn:
            already_open = incidents.get_open_by_rule_and_service(
                conn, alert.rule, alert.service
            )

        if already_open is not None:
            logger.info("alert joined open incident", extra={
                ARGUS_INCIDENT_ID: str(already_open.id), "rule": alert.rule
            })
            return str(already_open.id)

    # The row and the story's first line, in one transaction. Published from
    # here because by the time a node runs the alert has already been received;
    # published before the commit because an incident whose account begins
    # nowhere is the failure `publish_beside` exists to prevent.
    with connections() as conn:
        incident_id = incidents.create(conn, alert, trace_context)
        acknowledge_alert(conn, incident_id, alert, publisher_for)
        conn.commit()

    with connections() as conn:
        runs.enqueue(conn, incident_id)

    logger.info("incident opened", extra={
        ARGUS_INCIDENT_ID: incident_id, "service": alert.service, "rule": alert.rule
    })

    return incident_id
