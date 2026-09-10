"""Looking for a permanent fix, once no reversible action is left."""

from __future__ import annotations

from typing import Any

from agent_codefix import propose_fix
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus

from orchestrator.walk.narrating import Narration
from orchestrator.walk.routes import ESCALATED_ROUTE, RESOLVED_ROUTE


def codefix_node(state: IncidentState) -> dict[str, Any]:
    """Looks for a permanent fix, once no reversible action is left (spec §7.4).

    Still a stub, and the return value is the honest part of it: reporting that
    no fix was found is a real answer, and it is what carries the incident on to
    a human. Leaving it silent was how an incident could reach the end of the
    graph still marked `fixing`, which is a status nothing was working on.
    """
    propose_fix(state.hypothesis.summary if state.hypothesis else "")

    return {
        "fix_found": False,
        "narration": Narration(
            action="no code-level fix found",
            result="the incident is being handed to a human",
        ),
    }


def route_after_codefix(state: IncidentState) -> str:
    return RESOLVED_ROUTE if state.status == IncidentStatus.RESOLVED else ESCALATED_ROUTE
