from __future__ import annotations

from pydantic import BaseModel

from .action import Action
from .alert import Alert
from .attempt import Attempt
from .hypothesis import Hypothesis
from .incident_status import IncidentStatus


class IncidentState(BaseModel):
    """LangGraph `StateGraph` state (spec §7.1), mirroring the Postgres
    schema (§11.1) with the slice this change's stub nodes read/write."""

    incident_id: str
    alert: Alert
    status: IncidentStatus
    # The candidate under test - the one the gate judges and Mitigation acts
    # on. Kept beside the list rather than derived at every use, because every
    # node downstream asks "the hypothesis this incident is about", and making
    # each of them index into a list would be four chances to index differently.
    hypothesis: Hypothesis | None = None
    # Every explanation the investigation offered, best first, and how far along
    # them the walk has got. The list is what makes a refuted mitigation
    # something other than a dead end: being wrong about a correlated change is
    # the ordinary case, and the second explanation is usually still on it.
    candidates: list[Hypothesis] = []
    candidate_index: int = 0
    # What has already been tried and did not help. Carried into a later
    # investigation as evidence - it is the one thing a second round knows that
    # the first could not.
    attempts: list[Attempt] = []
    # Whether a further, wider investigation would read anything new, and where
    # it would start. Both come from the investigation itself, which owns the
    # widening schedule.
    can_widen: bool = False
    resume_from: int = 0
    # How many times this incident has been investigated. What bounds the walk,
    # because what buys a later round is the refutation rather than the window:
    # an attempt that failed is evidence no amount of reading produces, and a
    # hard incident has usually spent its whole widening schedule by the time
    # the first attempt comes back refuted.
    rounds: int = 0
    # Chosen by Mitigation and inspected by the tier gate before anything
    # mutating runs (spec §13). It lives in the graph's state rather than being
    # passed between the two, because a gate the acting node could bypass by
    # re-deriving the action would guard nothing.
    proposed_action: Action | None = None
    # Derivable from `hypothesis`, kept because the graph's state is what the
    # Dashboard reads (§7.7) and a confidence-over-time view wants it flat.
    confidence: float | None = None
    action_outcome: str | None = None