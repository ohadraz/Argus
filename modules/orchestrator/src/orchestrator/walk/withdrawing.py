"""The one way out of the walk that is the same wherever it is asked."""

from __future__ import annotations

from collections.abc import Callable

from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus

from orchestrator.walk.routes import WITHDRAWN_ROUTE


def stopping_when_withdrawn(
    route: Callable[[IncidentState], str]
) -> Callable[[IncidentState], str]:
    """Wraps a router so a withdrawn incident leaves the graph instead of
    going round it again.

    Applied at registration to every router, for the reason `with_status` is
    applied to every node: five routers cannot each be trusted to remember, and
    the one that forgot would be the loop. A withdrawn incident has nowhere to
    go by definition, so this is the one routing decision that is the same
    wherever in the walk it is asked.

    The key is `withdrawn` rather than `END` itself, because LangGraph resolves
    what a router returns through the mapping given to `add_conditional_edges` -
    so every one of those mappings carries the entry, and the destination stays
    stated where the rest of the graph's shape is.
    """
    def routed(state: IncidentState) -> str:
        if state.status == IncidentStatus.WITHDRAWN:
            return WITHDRAWN_ROUTE

        return route(state)

    return routed
