from __future__ import annotations

from functools import partial
from typing import Any, Final

from argus_core.config import get_settings
from argus_core.models.actor import Actor
from argus_core.models.incident_state import IncidentState

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator.walk.assembling import Collaborators
from orchestrator.walk.choosing import (
    next_candidate_node,
    route_after_next_candidate,
)
from orchestrator.walk.closing import postmortem_node
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.gating import route_after_gate, tier_gate_node
from orchestrator.walk.investigating import (
    investigator_node,
    route_after_investigation,
)
from orchestrator.walk.mitigating import mitigation_node, route_after_mitigation
from orchestrator.walk.narrating import with_status
from orchestrator.walk.proposing import mitigation_proposal_node
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    INVESTIGATING_ROUTE,
    MITIGATING_ROUTE,
    NEXT_CANDIDATE_ROUTE,
    RESOLVED_ROUTE,
    WITHDRAWN_ROUTE,
)
from orchestrator.walk.withdrawing import stopping_when_withdrawn

# The names LangGraph knows each node by. Every one is stated twice - once
# where the node is registered, and once as the destination a router's map
# resolves to - so a typo in either is a `KeyError` at walk time, in
# whichever run first takes that edge.
INVESTIGATOR_NODE: Final = "investigator"
MITIGATION_PROPOSAL_NODE: Final = "mitigation_proposal"
TIER_GATE_NODE: Final = "tier_gate"
MITIGATION_NODE: Final = "mitigation"
NEXT_CANDIDATE_NODE: Final = "next_candidate"
CODEFIX_NODE: Final = "codefix"
POSTMORTEM_NODE: Final = "postmortem"


# One attempt is four traversals - proposal, gate, mitigation, next_candidate -
# and an incident nobody could fix ends in two more: codefix, postmortem. Named
# constants rather than a number in the arithmetic below, because they are
# facts about the graph a few lines further down, and the day one of them
# changes is the day this stops being right silently.
_NODES_PER_ATTEMPT = 4
_NODES_ENDING_A_WALK = 2


def recursion_limit(max_rounds: int, max_candidates: int) -> int:
    """How many traversals the longest walk these settings allow will take.

    LangGraph stops a graph after a fixed number of super-steps, defaulting to
    25 - a number chosen to catch a runaway loop, and one this graph's walk
    passes legitimately: three rounds of four candidates is fifty-four. Hitting
    it raises mid-incident, with production already changed and no postmortem
    written, which is the one failure a limit meant to protect the system would
    cause by itself.

    Derived from the two settings that actually bound the walk rather than set
    to a generous constant, so that widening the iteration budget or the
    candidate budget cannot leave the graph unable to spend it.
    """
    a_full_round = 1 + _NODES_PER_ATTEMPT * max_candidates

    return max_rounds * a_full_round + _NODES_ENDING_A_WALK


def build_graph(checkpointer: BaseCheckpointSaver[Any],
                collaborators: Collaborators) -> CompiledStateGraph[IncidentState]:
    """Assembles spec §10's incident FSM as a LangGraph `StateGraph` (§7.1) -
    every sub-agent and the tier-gate node are present, and every edge from
    §10's diagram is wired.

    Nothing here knows where a collaborator came from. A node names what it
    needs, `Collaborators` says what a deployment supplied, and this hands the
    two together - so a walk in a different process, against a different pool,
    is the same graph built with a different record.

    Every node is wrapped so the status its work implies is derived, written
    and published in one place. The actor is supplied here because which agent
    a node belongs to is a fact about the graph, not about the node."""
    graph: StateGraph[IncidentState] = StateGraph(IncidentState)

    deciding_status = partial(
        with_status,
        max_rounds=get_settings().investigation_max_rounds,
        transition_incident=collaborators.transition_incident,
        record_note=collaborators.record_note,
        still_wanted=collaborators.still_wanted
    )

    graph.add_node(
        INVESTIGATOR_NODE,
        deciding_status(
            partial(investigator_node,
                    investigate=collaborators.investigate,
                    record_hypothesis=collaborators.record_hypothesis,
                    publisher=collaborators.publisher,
                    recorder=collaborators.recorder),
            Actor.INVESTIGATOR
        )
    )
    graph.add_node(
        MITIGATION_PROPOSAL_NODE,
        deciding_status(
            partial(mitigation_proposal_node,
                    fetch_flag_changes=collaborators.fetch_flag_changes,
                    publisher=collaborators.publisher),
            Actor.MITIGATION
        )
    )
    graph.add_node(
        TIER_GATE_NODE,
        deciding_status(
            partial(tier_gate_node, record_outcome=collaborators.record_outcome),
            Actor.MITIGATION
        )
    )
    graph.add_node(
        MITIGATION_NODE,
        deciding_status(
            partial(mitigation_node,
                    take=collaborators.take,
                    record_action=collaborators.record_action,
                    complete_action=collaborators.complete_action,
                    already_taken=collaborators.already_taken,
                    claimed_at=collaborators.claimed_at,
                    change_landed=collaborators.change_landed,
                    record_outcome=collaborators.record_outcome,
                    still_wanted=collaborators.still_wanted,
                    publisher=collaborators.publisher),
            Actor.MITIGATION
        )
    )
    graph.add_node(
        NEXT_CANDIDATE_NODE,
        deciding_status(
            next_candidate_node,
            Actor.MITIGATION
        )
    )
    graph.add_node(CODEFIX_NODE, deciding_status(codefix_node, Actor.CODEFIX))
    graph.add_node(
        POSTMORTEM_NODE,
        deciding_status(
            partial(postmortem_node,
                    write=collaborators.write_postmortem,
                    record=collaborators.record_postmortem),
            Actor.POSTMORTEM
        )
    )

    graph.add_edge(START, INVESTIGATOR_NODE)
    # Every router is wrapped so a withdrawn incident leaves the graph from
    # wherever it happens to be, and every mapping carries the destination for
    # that - the walk is over, and the nodes that write an ending are for
    # endings Argus reached.
    graph.add_conditional_edges(
        INVESTIGATOR_NODE,
        stopping_when_withdrawn(route_after_investigation),
        {
            MITIGATING_ROUTE: MITIGATION_PROPOSAL_NODE,
            ESCALATED_ROUTE: POSTMORTEM_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    graph.add_edge(MITIGATION_PROPOSAL_NODE, TIER_GATE_NODE)
    graph.add_conditional_edges(
        TIER_GATE_NODE,
        stopping_when_withdrawn(route_after_gate),
        {
            MITIGATING_ROUTE: MITIGATION_NODE,
            NEXT_CANDIDATE_ROUTE: NEXT_CANDIDATE_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    graph.add_conditional_edges(
        MITIGATION_NODE,
        stopping_when_withdrawn(route_after_mitigation),
        {
            RESOLVED_ROUTE: POSTMORTEM_NODE,
            NEXT_CANDIDATE_ROUTE: NEXT_CANDIDATE_NODE,
            ESCALATED_ROUTE: POSTMORTEM_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    # The loop. An attempt that settled nothing goes back to the proposal node
    # for the next explanation, or back to the Investigator for a wider look -
    # and Code-Fix is reached only once neither is left, which is what "Argus is
    # out of moves" actually means.
    graph.add_conditional_edges(
        NEXT_CANDIDATE_NODE,
        stopping_when_withdrawn(route_after_next_candidate),
        {
            MITIGATING_ROUTE: MITIGATION_PROPOSAL_NODE,
            INVESTIGATING_ROUTE: INVESTIGATOR_NODE,
            FIXING_ROUTE: CODEFIX_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    graph.add_conditional_edges(
        CODEFIX_NODE,
        stopping_when_withdrawn(route_after_codefix),
        {
            RESOLVED_ROUTE: POSTMORTEM_NODE,
            ESCALATED_ROUTE: POSTMORTEM_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    graph.add_edge(POSTMORTEM_NODE, END)

    return graph.compile(checkpointer=checkpointer)
