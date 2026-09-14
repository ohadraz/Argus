"""Looking for a permanent fix, once no reversible action is left."""

from __future__ import annotations

from agent_codefix import propose_fix
from argus_core.models import IncidentStatus

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.routes import ESCALATED_ROUTE, RESOLVED_ROUTE
from orchestrator.walk.state import IncidentState


def codefix_node(state: IncidentState) -> StateDelta:
    """Looks for a permanent fix, once no reversible action is left (spec §7.4).

    Still a stub, and the return value is the honest part of it: reporting that
    no fix was found is a real answer, and it is what carries the incident on to
    a human. Leaving it silent was how an incident could reach the end of the
    graph still marked `fixing`, which is a status nothing was working on.
    """
    propose_fix(state.hypothesis.summary if state.hypothesis else "")

    return StateDelta(
        fix_found=False,
        narration=Narration(
            action="no code-level fix found",
            detail="no code-level fix found, so the incident goes to a human",
        ),
    )


def route_after_codefix(state: IncidentState) -> str:
    return RESOLVED_ROUTE if state.status == IncidentStatus.RESOLVED else ESCALATED_ROUTE
