"""How an incident starts - and nothing about how one is walked.

Here rather than in `orchestrator` so that the process receiving alerts cannot
invoke the graph even by accident. `orchestrator.entrypoint` builds the
compiled graph at import time's first call and pulls the whole of langgraph in
with it; anything importing it can run an incident, and a web process that can
run an incident eventually does.

The split is therefore the point rather than tidiness, and it is now a package
boundary rather than a convention: `web_app` depends on this package and not
on `orchestrator`, so langgraph is never installed in the web process at all.
What walks is the worker's, in its own process.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import psycopg
from core import Connections, unit_of_work, utc_now
from core.models import ALERT_FIRING, Alert, IncidentStatus
from core.telemetry import ARGUS_INCIDENT_ID

from incident_record.publishing import PublisherFor, acknowledge_alert
from incident_record.repository import incidents, references, runs

logger = logging.getLogger(__name__)

# Puts one incident's walk in line, on the connection it is handed, inside its
# transaction, and returns the run's id.
type Enqueue = Callable[[psycopg.Connection, str], str]


@dataclass(frozen=True)
class _Joined:
    """An incident already there that an alert belongs to, and the line saying
    why that one."""

    incident_id: str
    said: str
    because: Mapping[str, object]


def start_incident(alert: Alert,
                   connections: Connections,
                   publisher_for: PublisherFor,
                   trace_context: Mapping[str, str] = incidents.NO_TRACE_CONTEXT,
                   enqueue: Enqueue = runs.enqueue) -> str:
    """The Orchestrator's entrypoint (spec §7.1): creates the `Incident` row
    and puts its walk in line - or, for a rule whose incident is still open or
    a firing an incident already holds, answers with that incident - called by
    `web_app` (§7.9) with a normalized `Alert` domain object - never a
    vendor's raw payload.

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
    an incident - an open one, or one holding its firing - keeps nothing: the
    incident's trace is the first alert's.

    One transaction, from the look for an incident already there to the walk
    put in line. An incident written without its walk would be one nobody
    walks and, never ending, one its rule joins for good, silencing the rule.
    And one delivery for a service at a time (`incidents.take_in_alone`): a
    delivery deciding while another is still writing would find nothing, and
    open a second incident for one fault. `enqueue` is the walk's half of that
    write, a seam so a failure inside it can be brought about on purpose.

    Its lines name the incident themselves, under the key a walk's lines are
    stamped with: nothing is walking it yet, so there is no baggage to stamp
    them from. They are said once the write has committed, so none speaks of
    an incident that was rolled back.
    """
    with unit_of_work(connections) as conn:
        incidents.take_in_alone(conn, alert.service)

        joined = _the_incident_it_belongs_to(conn, alert)

        if joined is not None:
            incident_id = joined.incident_id
            # A rule firing again can come from a new alert group, which the
            # monitor pages for under a key of its own, and a reminder can carry
            # firings the first notification did not. Either is about this
            # incident, so its names are this incident's too.
            references.add(conn, incident_id, alert.references)
        else:
            # One instant for the row and the sentence opening its account,
            # taken once the wait for any other delivery is over. Published
            # from here because by the time a node runs the alert has already
            # been received; published before the commit because an incident
            # whose account begins nowhere is the failure `publish_beside`
            # exists to prevent.
            opened_at = utc_now()
            incident_id = incidents.create(conn, alert, trace_context, at=opened_at)
            references.add(conn, incident_id, alert.references)
            acknowledge_alert(conn, incident_id, alert, publisher_for, at=opened_at)
            enqueue(conn, incident_id)

    if joined is not None:
        logger.info(joined.said, extra={ARGUS_INCIDENT_ID: incident_id, **joined.because})
    else:
        logger.info("incident opened", extra={
            ARGUS_INCIDENT_ID: incident_id, "service": alert.service, "rule": alert.rule
        })

    return incident_id


def _the_incident_it_belongs_to(conn: psycopg.Connection, alert: Alert) -> _Joined | None:
    """The incident already there that `alert` is about, if there is one."""
    # A rule that fired again for a service while its incident there is still
    # going on is that incident, not a second one. An alert naming no rule has
    # nothing to be joined by.
    if alert.rule is not None:
        already_open = incidents.get_open_by_rule_and_service(conn, alert.rule, alert.service)

        if already_open is not None:
            return _Joined(str(already_open.id), "alert joined open incident",
                           {"rule": alert.rule})

    # A firing an incident already holds is the monitor reminding Argus of an
    # alert it was told about, and is that incident however it ended - the
    # alarm still going is what an escalation, a recommendation, a disproof or
    # a person's ending each predicts. Except a mitigation: Argus said the
    # symptom stopped, and an alarm still going is the world contradicting
    # that, which is an incident to walk.
    firings = [reference.value for reference in alert.references
               if reference.kind == ALERT_FIRING]

    if firings:
        belongs_to = incidents.get_newest_by_names_and_service(
            conn, ALERT_FIRING, firings, alert.service
        )

        if belongs_to is not None and belongs_to.status != IncidentStatus.MITIGATED:
            return _Joined(str(belongs_to.id), "alert joined the incident of its firing",
                           {"status": belongs_to.status})

    return None
