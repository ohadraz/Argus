"""Turning an incident's rows back into one incident (spec §7.6).

The Postmortem agent holds no connection and reads no rows; what it needs is
scattered across the tables this module owns, and assembling it is the
Orchestrator's work. Keeping the gathering here is also what stops two readers
of the same incident disagreeing: the page and the postmortem read the same
account, through the same repositories.

Nothing here decides anything. Every line comes from something recorded while
it was happening, rendered for a reader - which is the point, because what
happened was settled then, and a postmortem re-deriving it from conclusions
would be describing a different incident.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

import psycopg
from agent_postmortem import IncidentEvidence, PostmortemDocument, write_postmortem
from agent_postmortem.sources import EngagementAnswer
from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.events import LogsRetrieved, OnsetDetected
from argus_core.llm.client import LLMClient
from argus_core.models.metrics import MetricBucket
from argus_core.replay import Recorder, Replay
from argus_core.replay import nobody as records_nothing
from argus_core.timestamps import parse_iso, to_iso

from orchestrator.rates import todays_rates
from orchestrator.repository import actions, events, hypotheses, incidents, replay, timeline


def write_postmortem_for(incident_id: str,
                         recorder: Recorder = records_nothing) -> PostmortemDocument:
    """The real postmortem for one incident: gather, then write.

    The two sources nothing answers yet are wired to say so rather than left
    out. An unwired port that returned zero would put "this incident cost
    nothing" in front of a reader as though it had been measured, and the
    document is built to tell those apart.
    """
    with connect() as conn:
        evidence = gather_evidence(conn, incident_id)
        rates = todays_rates(conn, get_settings().reporting_currency)

    return write_postmortem(
        evidence,
        revenue=_the_shops_takings,
        rates=lambda: rates,
        engagement=_no_engagement_source,
        metrics=_metrics_between,
        llm=_a_recording_client(Replay(incident_id, recorder))
    )


def _the_shops_takings(started_at: datetime,
                       ended_at: datetime) -> Mapping[str, Decimal] | None:
    """What the shop took over the incident, read from the payment provider.

    Imported inside for the same reason the metrics channel is: choosing this
    pulls in a vendor's SDK, and a unit test of the gathering above should not
    have to have one installed.

    A provider that cannot be read - or a deployment holding no credential -
    answers `None` rather than zero. The agent already knows what to do with an
    unanswered question, and "the incident cost nothing" is not it.
    """
    from revenue_source import taken_between
    from revenue_source.stripe_adapter import charges_between

    takings = taken_between(started_at, ended_at, charges=charges_between)

    return takings.amounts if takings is not None else None


def _no_engagement_source(dont_care_incident_id: str) -> EngagementAnswer | None:
    """No source of responder timings exists yet - a PagerDuty-shaped one is
    the change after next."""
    return None


def _metrics_between(window_start: datetime, window_end: datetime) -> list[MetricBucket]:
    """The metrics channel, asked for a window spanning the whole incident.

    Imported inside because the read tier is a running process: a unit test of
    the gathering above should not pay for a client that expects one.
    """
    from read_mcp_client import get_metrics_summary

    return get_metrics_summary(window_start=to_iso(window_start),
                               window_end=to_iso(window_end))


def _a_recording_client(replay: Replay) -> LLMClient:
    """The configured model, wrapped so this call keeps a receipt too.

    Deferred like the investigator's, and for the same reason: choosing a
    client pulls in a vendor's SDK, which nothing testing the gathering should
    have to import.
    """
    from argus_core.llm.client_selection import get_llm_client

    return get_llm_client(replay)


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
        tokens_spent=replay.get_tokens_spent(conn, incident_id)
    )


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
    """The narration, as the page shows it: who did what, in order."""
    return [
        f"{to_iso(event.created_at)} {event.to_status} - {event.actor}: {event.action}"
        + (f" ({event.result})" if event.result else "")
        for event in timeline.get_timeline_events(conn, incident_id)
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
        f"{action.type or 'action'} on {action.target} - "
        f"{action.outcome or 'no verdict recorded'}"
        for action in actions.get_by_incident(conn, incident_id)
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
