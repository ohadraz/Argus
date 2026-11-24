"""Everything the view is allowed to know about an incident.

One place, because the incident page and the fragment it polls ask the same
question and would otherwise ask it twice, in two slightly different ways. It
reads through the incident record's roles and writes no SQL of its own:
`web_app` holds no incident-domain logic (spec §7.9), and a query here would be
the beginning of a second opinion about what an incident is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

import psycopg
from incident_record import incident_reads_on, incidents_on_show_on
from narration import ShownRevision
from postmortem_rendering import (
    RenderedPostmortem,
    ReportedResolution,
    SynopsisLines,
    render,
    the_reported_resolution,
    the_synopsis,
)

from web_app.views import (
    IncidentDetail,
    IncidentSummary,
    LiveIncident,
    Story,
    build_incident_detail,
    build_incident_summary,
    build_live_incident,
    build_story,
)


def read_history(conn: psycopg.Connection) -> list[IncidentSummary]:
    """Every incident, in the order the repository returns them."""
    return [build_incident_summary(incident)
            for incident in incidents_on_show_on(conn).recent()]


def read_incident(conn: psycopg.Connection,
                  incident_id: str,
                  minutes: Sequence[str] = (),
                  logged: Sequence[str] = (),
                  revisions: Mapping[str, ShownRevision] | None = None
                  ) -> IncidentDetail | None:
    """One incident's whole walk, or `None` where there is no such incident.

    `None` rather than an empty detail: an id that never existed has no walk to
    be empty, and the caller owes a reader that distinction.

    Five reads rather than one join, because each is a repository's own
    question and the join belongs to the view, which is where the answers are
    arranged for somebody to look at. `minutes` and `logged` are the rows the
    page beside the walk holds, for its findings to lead to, and `revisions`
    the revisions it names short, for its candidates to say alike.
    """
    reads = incident_reads_on(conn)
    incident = reads.incident(incident_id)
    if incident is None:
        return None

    return build_incident_detail(
        incident,
        candidates=reads.candidates(incident_id),
        attempts=reads.actions(incident_id),
        account=reads.account(incident_id),
        minutes=minutes,
        logged=logged,
        revisions=revisions or {}
    )


def read_live_incident(conn: psycopg.Connection) -> LiveIncident | None:
    """The incident somebody opening Argus is looking for, or `None` when there
    has never been one.

    Which incident that is belongs to the repository - "the newest one still
    running, else the newest there is" is a question about the rows, and
    answering it here would be this page deciding what counts as current.
    """
    incident = incidents_on_show_on(conn).current()

    if incident is None:
        return None

    return build_live_incident(incident, incident_reads_on(conn).account(incident.id))


def read_story(conn: psycopg.Connection, incident_id: str) -> Story:
    """One incident's account of its own work: what it did, and what it read.

    Empty for an incident that recorded nothing, which is a real answer: an
    incident from before the stream existed, or one that escalated before
    anything looked at it.
    """
    return build_story(incident_reads_on(conn).account(incident_id))


def read_postmortem(conn: psycopg.Connection,
                    incident: IncidentDetail,
                    address_of: Callable[[str], str]) -> RenderedPostmortem | None:
    """The postmortem as it is read, where one has been written.

    Rendered here, from the row and the incident's events, so the page and the
    PDF are handed the same document. `address_of` gives an incident's page by
    its full address, which only the request knows.
    """
    reads = incident_reads_on(conn)
    postmortem = reads.postmortem(incident.id)
    if postmortem is None:
        return None

    return render(postmortem, incident.alert, reads.account(incident.id), address_of)


def read_synopsis(conn: psycopg.Connection,
                  incident: IncidentDetail,
                  postmortem_at: str) -> SynopsisLines | None:
    """The executive synopsis as it is read, where one was written and not
    given up - and so sent. `postmortem_at` is the full postmortem's address,
    which only the request knows."""
    reads = incident_reads_on(conn)
    synopsis = reads.synopsis(incident.id)
    postmortem = reads.postmortem(incident.id)
    if synopsis is None or synopsis.overview is None or postmortem is None:
        return None

    return the_synopsis(synopsis, postmortem, incident.alert,
                        the_reported_resolution(reads.account(incident.id)),
                        postmortem_at)


def read_resolution(conn: psycopg.Connection, incident_id: str) -> ReportedResolution | None:
    """Who resolved the incident, where a person did."""
    return the_reported_resolution(incident_reads_on(conn).account(incident_id))
