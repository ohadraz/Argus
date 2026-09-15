"""Looking for a permanent fix, once no reversible action is left."""

from __future__ import annotations

from argus_core.models import IncidentStatus

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import ProposeFix
from orchestrator.walk.routes import ESCALATED_ROUTE, RESOLVED_ROUTE
from orchestrator.walk.state import IncidentState


def codefix_node(state: IncidentState, propose_fix: ProposeFix) -> StateDelta:
    """Looks for a permanent fix, once no reversible action is left (spec §7.4).

    What the agent answered is what this reports. It used to call Code-Fix and
    discard the reply while stating that no fix was found, which was true of
    today's stub and would have gone on being stated the day the agent proposed
    something - a graph escalating past a fix it had been handed, failing in a
    way that would read as the agent's bug rather than as a node that never
    listened.

    The agent is asked even when the walk concluded nothing, about nothing.
    "I looked and found no fix" and "nobody looked" reach the same human and
    only one of them would be true.

    Reporting either answer is the other half of it: an incident that reached
    here and said nothing ended the graph still marked `fixing`, which is a
    status nothing was working on.
    """
    fix = propose_fix(state.hypothesis.summary if state.hypothesis else "")

    if fix is None:
        return StateDelta(
            fix_found=False,
            narration=Narration(
                action="no code-level fix found",
                detail="no code-level fix found, so the incident goes to a human",
            ),
        )

    return StateDelta(
        fix_found=True,
        narration=Narration(action="a code-level fix was proposed", detail=fix),
    )


def route_after_codefix(state: IncidentState) -> str:
    return RESOLVED_ROUTE if state.status == IncidentStatus.RESOLVED else ESCALATED_ROUTE
