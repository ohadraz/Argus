from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, Final

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.models import Actor, IncidentStatus
from argus_incidents import wanted_until_a_person_ends_it
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from orchestrator.walk.assembling import Collaborators
from orchestrator.walk.choosing import (
    next_candidate_node,
    route_after_next_candidate,
)
from orchestrator.walk.closing import postmortem_node
from orchestrator.walk.ending import stopping_when_a_person_ended_it
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.gating import route_after_gate, tier_gate_node
from orchestrator.walk.investigating import (
    investigator_node,
    route_after_investigation,
)
from orchestrator.walk.mitigating import mitigation_node, route_after_mitigation
from orchestrator.walk.narrating import waits_for_nobody, with_status
from orchestrator.walk.proposing import mitigation_proposal_node
from orchestrator.walk.remembering import remembering_node
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    INVESTIGATING_ROUTE,
    MITIGATING_ROUTE,
    NEXT_CANDIDATE_ROUTE,
    POSTMORTEM_ROUTE,
    RESOLVED_ROUTE,
    WITHDRAWN_ROUTE,
)
from orchestrator.walk.state import IncidentState
from orchestrator.walk.tracing import traced

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
REMEMBERING_NODE: Final = "remembering"
POSTMORTEM_NODE: Final = "postmortem"


# One attempt is four traversals - proposal, gate, mitigation, next_candidate -
# and an incident nobody could fix ends in three more: codefix, remembering,
# postmortem. Named constants rather than a number in the arithmetic below,
# because they are facts about the graph a few lines further down, and the day
# one of them changes is the day this stops being right silently.
_NODES_PER_ATTEMPT = 4
_NODES_ENDING_A_WALK = 3


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
    a node belongs to is a fact about the graph, not about the node.

    And every node is a step of the walk's trace, registered through `step` so
    that none can be added without one - the agent named beside it is what the
    step's span, and every model call made inside it, say they were."""
    graph: StateGraph[IncidentState] = StateGraph(IncidentState)

    def step(name: str, actor: Actor, node: Callable[[IncidentState], Any]) -> None:
        """Registers a node, traced as a step of the walk that `actor` took."""
        graph.add_node(name, traced(name, actor, node))

    deciding_status = partial(
        with_status,
        max_rounds=collaborators.max_rounds,
        transition_incident=collaborators.transition_incident,
        ended_by_a_person=collaborators.ended_by_a_person,
        wait_for_people=collaborators.wait_for_people
    )
    # The yes-or-no the nodes hand their agents. Either ending is a reason not
    # to take the next step; where the walk goes after stopping is the routers'.
    still_wanted = wanted_until_a_person_ends_it(collaborators.ended_by_a_person)

    step(
        INVESTIGATOR_NODE, Actor.INVESTIGATOR,
        deciding_status(
            partial(investigator_node,
                    investigate=collaborators.investigate,
                    recall_similar=collaborators.recall_similar,
                    record_hypothesis=collaborators.record_hypothesis,
                    fetch_flag_changes=collaborators.fetch_flag_changes,
                    fetch_dependencies=collaborators.fetch_dependencies,
                    fetch_deployments=collaborators.fetch_deployments,
                    publisher=collaborators.publisher,
                    recorder=collaborators.recorder,
                    still_wanted=still_wanted)
        )
    )
    step(
        MITIGATION_PROPOSAL_NODE, Actor.ORCHESTRATOR,
        deciding_status(mitigation_proposal_node)
    )
    step(
        TIER_GATE_NODE, Actor.ORCHESTRATOR,
        deciding_status(
            partial(tier_gate_node,
                    record_outcome=collaborators.record_outcome,
                    admitted=collaborators.admitted,
                    attempts_per_subject=collaborators.attempts_per_subject,
                    publisher=collaborators.publisher)
        )
    )
    step(
        MITIGATION_NODE, Actor.MITIGATION,
        deciding_status(
            partial(mitigation_node,
                    take=collaborators.take,
                    record_action=collaborators.record_action,
                    complete_action=collaborators.complete_action,
                    already_taken=collaborators.already_taken,
                    change_landed=collaborators.change_landed,
                    record_outcome=collaborators.record_outcome,
                    still_wanted=still_wanted,
                    publisher=collaborators.publisher)
        )
    )
    step(
        NEXT_CANDIDATE_NODE, Actor.ORCHESTRATOR,
        deciding_status(
            partial(next_candidate_node,
                    publisher=collaborators.publisher,
                    max_rounds=collaborators.max_rounds)
        )
    )
    step(
        CODEFIX_NODE, Actor.CODEFIX,
        deciding_status(
            partial(codefix_node,
                    propose_fix=collaborators.propose_fix,
                    publisher=collaborators.publisher,
                    still_wanted=still_wanted)
        )
    )
    # Not wrapped in `deciding_status`, unlike every node above it. Filing what
    # was tried changes nothing about where the incident stands - it is already
    # over - and a status derived again here would be the same status published
    # twice.
    step(
        REMEMBERING_NODE, Actor.ORCHESTRATOR,
        partial(remembering_node,
                actions_taken=collaborators.actions_taken,
                remember=collaborators.remember_incident,
                publisher=collaborators.publisher)
    )
    # Stopped only by a withdrawal. A person who reported the incident resolved
    # is owed the write-up; the person who took it back is not waiting to be
    # told what Argus made of it.
    step(
        POSTMORTEM_NODE, Actor.POSTMORTEM,
        deciding_status(
            partial(postmortem_node,
                    write=collaborators.write_postmortem,
                    record=collaborators.record_postmortem),
            stops_for=frozenset({IncidentStatus.WITHDRAWN}),
            # The last step: there is nothing after it to hold off.
            wait_for_people=waits_for_nobody
        )
    )

    graph.add_edge(START, INVESTIGATOR_NODE)
    # Every router is wrapped so an incident a person ended goes where that
    # ending sends it from wherever the walk happens to be, and every mapping
    # carries both destinations. A withdrawn incident leaves the graph - the
    # walk is over, and nothing is written up for it. A resolved one goes on to
    # be remembered and written up, past anything still to try.
    graph.add_conditional_edges(
        INVESTIGATOR_NODE,
        stopping_when_a_person_ended_it(route_after_investigation),
        {
            MITIGATING_ROUTE: MITIGATION_PROPOSAL_NODE,
            ESCALATED_ROUTE: REMEMBERING_NODE,
            RESOLVED_ROUTE: REMEMBERING_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    graph.add_edge(MITIGATION_PROPOSAL_NODE, TIER_GATE_NODE)
    graph.add_conditional_edges(
        TIER_GATE_NODE,
        stopping_when_a_person_ended_it(route_after_gate),
        {
            MITIGATING_ROUTE: MITIGATION_NODE,
            NEXT_CANDIDATE_ROUTE: NEXT_CANDIDATE_NODE,
            # An action the gate declined because nothing could confirm it. The
            # mitigation phase is over - no candidate after this one would be
            # any more confirmable - and what is left is the fault in the code,
            # which is where a mitigation that worked goes too.
            FIXING_ROUTE: CODEFIX_NODE,
            RESOLVED_ROUTE: REMEMBERING_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    graph.add_conditional_edges(
        MITIGATION_NODE,
        stopping_when_a_person_ended_it(route_after_mitigation),
        {
            # A mitigation that worked goes on to Code-Fix rather than to the
            # postmortem. The symptom is gone; the fault it exposed is still in
            # the code, and a flag holding a bug off is a thing somebody has to
            # come back to unless the bug gets fixed.
            FIXING_ROUTE: CODEFIX_NODE,
            NEXT_CANDIDATE_ROUTE: NEXT_CANDIDATE_NODE,
            ESCALATED_ROUTE: REMEMBERING_NODE,
            RESOLVED_ROUTE: REMEMBERING_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    # The loop. An attempt that settled nothing goes back to the proposal node
    # for the next explanation, or back to the Investigator for a wider look -
    # and Code-Fix is reached only once neither is left, which is what "Argus is
    # out of moves" actually means.
    graph.add_conditional_edges(
        NEXT_CANDIDATE_NODE,
        stopping_when_a_person_ended_it(route_after_next_candidate),
        {
            MITIGATING_ROUTE: MITIGATION_PROPOSAL_NODE,
            INVESTIGATING_ROUTE: INVESTIGATOR_NODE,
            FIXING_ROUTE: CODEFIX_NODE,
            RESOLVED_ROUTE: REMEMBERING_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    graph.add_conditional_edges(
        CODEFIX_NODE,
        stopping_when_a_person_ended_it(route_after_codefix),
        {
            POSTMORTEM_ROUTE: REMEMBERING_NODE,
            RESOLVED_ROUTE: REMEMBERING_NODE,
            WITHDRAWN_ROUTE: END
        }
    )
    # Remembering comes before the write-up rather than after it, so that
    # neither failure can take the other down. This node swallows its own,
    # leaving the postmortem to be written regardless; and a postmortem that
    # raises cannot then cost the next incident what this one learned.
    graph.add_edge(REMEMBERING_NODE, POSTMORTEM_NODE)
    graph.add_edge(POSTMORTEM_NODE, END)

    return graph.compile(checkpointer=checkpointer)
