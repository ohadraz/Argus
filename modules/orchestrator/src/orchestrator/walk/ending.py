"""The ways out of the walk that are the same wherever they are asked."""

from __future__ import annotations

from collections.abc import Callable

from argus_core.models import IncidentStatus

from orchestrator.walk.routes import RESOLVED_ROUTE, WITHDRAWN_ROUTE
from orchestrator.walk.state import IncidentState


def stopping_when_a_person_ended_it(
    route: Callable[[IncidentState], str]
) -> Callable[[IncidentState], str]:
    """Wraps a router so an incident a person ended goes where that ending
    sends it, instead of round the walk again.

    Applied at registration to every router, for the reason `with_status` is
    applied to every node: five routers cannot each be trusted to remember, and
    the one that forgot would be the loop. A person's ending is the one routing
    decision that is the same wherever in the walk it is asked.

    Two endings, two destinations. A withdrawn incident has nowhere to go - the
    person took it back, and its changes are put back on the way out. A resolved
    one goes on to be remembered and written up, because the person who
    reported it over is owed the postmortem and the next incident is owed what
    this one tried.

    The keys are routes rather than `END` or a node, because LangGraph resolves
    what a router returns through the mapping given to `add_conditional_edges` -
    so every one of those mappings carries both entries, and the destinations
    stay stated where the rest of the graph's shape is.
    """
    def routed(state: IncidentState) -> str:
        if state.status == IncidentStatus.WITHDRAWN:
            return WITHDRAWN_ROUTE

        if state.status == IncidentStatus.RESOLVED:
            return RESOLVED_ROUTE

        return route(state)

    return routed
