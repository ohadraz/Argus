"""Everything an incident left behind, handed over in one piece.

The agent holds no database connection. What it needs is scattered across four
tables the Orchestrator already owns - the incident's own row, its published
events, the candidates it ranked, the actions it took - and gathering them is
that module's business, not this one's. What arrives here is the result of
that gathering, in Argus's terms rather than in rows.

`tokens_spent` is summed rather than listed for the same reason: what the
replay log holds is one row per call, and adding them up is a query, not a
judgment.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IncidentEvidence(BaseModel):
    """One incident, as the postmortem reads it.

    The prose fields are lists of already-rendered lines rather than domain
    objects, because everything downstream of here either counts them or shows
    them to a model. A postmortem that re-derived the story from `Hypothesis`
    and `Action` rows would be re-deciding what happened, and what happened was
    decided while it was happening.
    """

    incident_id: str
    started_at: datetime
    ended_at: datetime
    # When the service actually began to fail, as the Investigator measured it
    # from the metrics - not when Argus was told. The two differ by however
    # long the alert took to fire, and those minutes are the worst ones to get
    # wrong: counted as calm, they inflate the baseline the loss is measured
    # against; left out of the incident, the damage they did is invisible.
    #
    # `None` where nothing measured one, in which case the alert's own time is
    # the best available answer and the document is written from that.
    onset_at: datetime | None = None
    alert_summary: str
    timeline: list[str]
    candidates: list[str]
    actions: list[str]
    log_lines: list[str]
    tokens_spent: int
