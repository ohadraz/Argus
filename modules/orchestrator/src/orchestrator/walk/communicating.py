"""The one page an incident gets, and what it says."""

from __future__ import annotations

from typing import Any

from agent_communicator import page as _page
from argus_core.models.incident_state import IncidentState

from orchestrator.walk.ports import Page


def communicator_node(state: IncidentState, page: Page = _page) -> dict[str, Any]:
    """Sends the one page an incident gets (spec §7.5, §10).

    Every way an incident can end without a fix arrives here - an investigation
    that named nothing, an action that could not be taken, a walk that tried
    everything it had - which is what makes "exactly one page" a property of
    the graph's shape rather than a rule this node has to enforce. The updates
    along the way were the Communicator's other register; this is the one that
    interrupts someone.
    """
    page(state.incident_id, _why_a_human_is_needed(state))
    return {}


def _why_a_human_is_needed(state: IncidentState) -> str:
    """What the page says, which is the last thing Argus gets to say.

    A walk that tried things and a walk that never got started are different
    incidents to be woken for, and the count is the difference: it tells the
    reader whether production has been changed and put back, or never touched.
    """
    if state.attempts:
        return (
            f"{len(state.attempts)} explanation(s) were tried and undone, and "
            f"nothing further is left to try"
        )

    return "There was no actions Argus could take."
