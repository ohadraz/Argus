from __future__ import annotations

import psycopg
from orchestrator.repository import (
    actions,
    events,
    hypotheses,
    incidents,
    postmortems,
    timeline,
)

from argus_web.views import (
    IncidentDetail,
    IncidentSummary,
    LiveIncident,
    PostmortemView,
    Story,
    build_incident_detail,
    build_incident_summary,
    build_live_incident,
    build_postmortem_view,
    build_story,
)

"""Everything the view is allowed to know about an incident.

One place, because the incident page and the fragment it polls ask the same
question and would otherwise ask it twice, in two slightly different ways. It
reads through the repositories that own the tables and writes no SQL of its
own: `argus_web` holds no incident-domain logic (spec §7.9), and a query here
would be the beginning of a second opinion about what an incident is.
"""


def read_history(conn: psycopg.Connection) -> list[IncidentSummary]:
    """Every incident, in the order the repository returns them."""
    return [build_incident_summary(incident) for incident in incidents.get_recent(conn)]


def read_incident(conn: psycopg.Connection, incident_id: str) -> IncidentDetail | None:
    """One incident's whole walk, or `None` where there is no such incident.

    `None` rather than an empty detail: an id that never existed has no walk to
    be empty, and the caller owes a reader that distinction.

    Four reads rather than one join, because each is a repository's own
    question and the join belongs to the view, which is where the answers are
    arranged for somebody to look at.
    """
    incident = incidents.get(conn, incident_id)
    if incident is None:
        return None

    return build_incident_detail(
        incident,
        candidates=hypotheses.get_all_by_incident(conn, incident_id),
        attempts=actions.get_by_incident(conn, incident_id),
        timeline=timeline.get_timeline_events(conn, incident_id),
    )


def read_live_incident(conn: psycopg.Connection) -> LiveIncident | None:
    """The incident somebody opening Argus is looking for, or `None` when there
    has never been one.

    Which incident that is belongs to the repository - "the newest one still
    running, else the newest there is" is a question about the rows, and
    answering it here would be this page deciding what counts as current.
    """
    incident = incidents.get_current(conn)

    if incident is None:
        return None

    return build_live_incident(incident, events.get_by_incident(conn, incident.id))


def read_story(conn: psycopg.Connection, incident_id: str) -> Story:
    """One incident's account of its own work: what it did, and what it read.

    Empty for an incident that recorded nothing, which is a real answer: an
    incident from before the stream existed, or one that escalated before
    anything looked at it.
    """
    return build_story(events.get_by_incident(conn, incident_id))


def read_postmortem(conn: psycopg.Connection, incident_id: str) -> PostmortemView | None:
    """The postmortem, where one has been written."""
    postmortem = postmortems.get_by_incident(conn, incident_id)

    return build_postmortem_view(postmortem) if postmortem is not None else None
