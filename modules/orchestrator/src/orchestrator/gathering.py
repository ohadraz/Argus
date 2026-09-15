"""Turning an incident's rows back into one incident (spec §7.6).

The Postmortem agent holds no connection and reads no rows; what it needs is
scattered across the tables `argus_incidents` owns, and assembling it is the
Orchestrator's work. Keeping the gathering here is also what stops two readers
of the same incident disagreeing: the page and the postmortem read the same
account, through the same repositories.

Nothing here decides anything. Every line comes from something recorded while
it was happening, rendered for a reader - which is the point, because what
happened was settled then, and a postmortem re-deriving it from conclusions
would be describing a different incident.
"""

from __future__ import annotations

from datetime import datetime

import psycopg
from agent_postmortem import IncidentEvidence, Sources, write_postmortem
from argus_core import Connections, parse_iso, to_iso
from argus_core.events import FixAttempted, LogsRetrieved, OnsetDetected
from argus_core.llm import ClientFor
from argus_core.models import OpenedPullRequest, PostmortemDocument
from argus_core.replay import Recorder, Replay
from argus_core.replay import nobody as records_nothing
from argus_incidents.repository import (
    events,
    hypotheses,
    incidents,
    replay,
    taken_actions,
)
from argus_narration import build_narration


def write_postmortem_for(incident_id: str,
                         connections: Connections,
                         sources: Sources,
                         client_for: ClientFor,
                         recorder: Recorder = records_nothing) -> PostmortemDocument:
    """The real postmortem for one incident: gather, then write.

    `sources` and `client_for` arrive as arguments rather than being built
    here. What this function does is read an incident's rows and hand them to
    the agent; which payment provider answers the revenue question, and which
    model writes the prose, are decisions belonging to whoever started the
    process - and building them here is what made this the one production path
    in the repo that could not be tested without a vendor SDK installed.

    Every port is answered by a source that says so when it cannot answer,
    rather than reporting a zero: "this incident cost nothing" in front of a
    reader looks measured, and the document is built to tell the two apart.

    `client_for` is a factory rather than a client, because the receipt is per
    incident: the wrapper holds the incident it records for, and one client
    shared across a process would file every incident's calls under whichever
    was written up first.
    """
    with connections() as conn:
        evidence = gather_evidence(conn, incident_id)

    return write_postmortem(
        evidence, sources, client_for(Replay(incident_id, recorder))
    )


def gather_evidence(conn: psycopg.Connection, incident_id: str) -> IncidentEvidence:
    """Everything one incident left behind, in the order it left it.

    Refuses an incident that has not ended. A postmortem is written once, when
    the incident is over, and a duration measured to "now" instead would be a
    different number every time anyone asked for one.
    """
    incident = incidents.get(conn, incident_id)
    if incident is None:
        raise ValueError(f"no incident [{incident_id}] to write a postmortem for")

    if incident.ended_at is None:
        raise ValueError(
            f"incident [{incident_id}] has not ended, and an incident still being "
            f"worked has no duration to report"
        )

    return IncidentEvidence(
        incident_id=incident_id,
        started_at=incident.created_at,
        ended_at=incident.ended_at,
        onset_at=_when_it_actually_began(conn, incident_id),
        alert_summary=_what_was_alerted(incident.alert_payload),
        timeline=_what_happened(conn, incident_id),
        candidates=_what_was_considered(conn, incident_id),
        actions=_what_was_done(conn, incident_id),
        log_lines=_what_was_read(conn, incident_id),
        tokens_spent=replay.get_tokens_spent(conn, incident_id),
        pull_request=_what_was_proposed(conn, incident_id)
    )


def _what_was_proposed(conn: psycopg.Connection,
                       incident_id: str) -> OpenedPullRequest | None:
    """The fix Code-Fix opened, as it published it.

    Off the event's own field rather than off the event's presence: the step
    publishes whether or not it proposed anything, and "Argus read the code and
    found nothing to change" is a finding rather than a missing proposal (§10).
    An incident with a `FixAttempted` and no pull request has to come back with
    none, or the document offers a reader a link to nowhere.

    The last one, for the same reason the walk loops at all: an incident that
    went back to investigate can reach the code twice, and what a reader wants
    is the proposal that stands rather than the one that was superseded.
    """
    proposed = [event.pull_request
                for event in events.get_by_incident(conn, incident_id)
                if isinstance(event, FixAttempted) and event.pull_request]

    return proposed[-1] if proposed else None


def _when_it_actually_began(conn: psycopg.Connection,
                            incident_id: str) -> datetime | None:
    """The onset the Investigator measured, as it published it.

    Read from the account rather than re-derived: the onset was found by
    walking the metrics for a departure from baseline while the incident was
    live, and a postmortem measuring it again from a wider window would date
    the same incident differently from the page that showed it.

    `None` where no onset was ever published - an incident that never reached
    an investigation, or one whose metrics could not be read. The document
    then falls back to the alert's own time, which is late but real.
    """
    onsets = [event.onset
              for event in events.get_by_incident(conn, incident_id)
              if isinstance(event, OnsetDetected)]

    return parse_iso(onsets[0]) if onsets else None


def _what_was_alerted(alert_payload: dict[str, object]) -> str:
    return f"{alert_payload.get('alert_name')} on {alert_payload.get('service')}"


def _what_happened(conn: psycopg.Connection, incident_id: str) -> list[str]:
    """The narration, as the page shows it: who did what, in order.

    The page's own renderer rather than a second one written here. The
    postmortem and the dashboard tell the same story, and two builders of it
    are two stories - the one a reader was shown while the incident ran, and a
    different one in the document written about it afterwards.

    Flattened to a line of text because that is what the model is handed. The
    structure a page uses to mark a flag or link a minute has no meaning in a
    prompt, and the sentence is the part that carries the account.
    """
    return [
        f"{to_iso(line.at)} {line.who}: {line.text}"
        for line in build_narration(events.get_by_incident(conn, incident_id))
    ]


def _what_was_considered(conn: psycopg.Connection, incident_id: str) -> list[str]:
    """Every candidate ranked, tried or not.

    The untried ones are half of what a walk has to say: an investigation that
    was confident and right and one that ran out of options are told apart by
    what was left on the list.
    """
    return [
        f"{hypothesis.summary} [{hypothesis.cause_type}, confidence "
        f"{hypothesis.confidence}, "
        f"{hypothesis.result if hypothesis.tested else 'never tried'}]"
        for hypothesis in hypotheses.get_all_by_incident(conn, incident_id)
    ]


def _what_was_done(conn: psycopg.Connection, incident_id: str) -> list[str]:
    return [
        f"{taken_action.type or 'action'} on {taken_action.target} - "
        f"{taken_action.outcome or 'no verdict recorded'}"
        for taken_action in taken_actions.get_by_incident(conn, incident_id)
    ]


def _what_was_read(conn: psycopg.Connection, incident_id: str) -> list[str]:
    """The log lines the incident actually saw.

    From the published account rather than from the log store, which has moved
    on since. A postmortem explaining lines Argus never read would be
    explaining a different incident, fluently.
    """
    return [
        line
        for event in events.get_by_incident(conn, incident_id)
        if isinstance(event, LogsRetrieved)
        for line in event.lines
    ]
