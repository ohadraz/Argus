"""The shape of the walk, and what a walk is allowed to cost.

Spec §10's diagram, written down twice - once as the graph the Orchestrator
assembles and once here - so that the two can be compared. Read off the
compiled graph rather than driven, which is the limit of what this can say: it
proves every edge exists, not that any router ever returns the key that takes
one - nor which route takes which edge, since two routes to one node are drawn
as a single edge. The walk itself is `component/`'s subject.

LangGraph ends a run that exceeds its recursion limit as failed, so the limit
has to be derived from the graph rather than picked: a verdict with one more
explanation than usual would otherwise end the incident on a recursion error,
with production already changed and no postmortem written.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import psycopg
import pytest
from argus_core.mcp_transport import McpClient
from argus_testkit import Assertion, Scenario
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from orchestrator.walk.assembling import against
from orchestrator.walk.graph import (
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    TIER_GATE_NODE,
    build_graph,
    recursion_limit,
)
from orchestrator.walk.state import IncidentState

type Edge = tuple[str, str]

NODES_PER_ATTEMPT = 4

EVERY_NODE_IN_THE_WALK = [
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    TIER_GATE_NODE
]

# Every edge of §10, as `(from, to)`. Pairs rather than routes: where two
# routes lead to one node - a code fix that worked and one that did not both
# reach the postmortem - LangGraph draws a single edge and keeps whichever
# label the mapping listed last, so a table of labels would assert an accident
# of ordering. Which route takes which edge is asserted where it is decided,
# in each router's own test.
EVERY_EDGE_IN_THE_WALK: frozenset[Edge] = frozenset({
    (START, INVESTIGATOR_NODE),

    (INVESTIGATOR_NODE, MITIGATION_PROPOSAL_NODE),
    (INVESTIGATOR_NODE, REMEMBERING_NODE),
    (INVESTIGATOR_NODE, END),

    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    (MITIGATION_PROPOSAL_NODE, TIER_GATE_NODE),

    (TIER_GATE_NODE, MITIGATION_NODE),
    (TIER_GATE_NODE, NEXT_CANDIDATE_NODE),
    (TIER_GATE_NODE, END),

    # A mitigation that worked still goes looking for a permanent fix: the flag
    # is back, and the fault it exposed is still in the code.
    (MITIGATION_NODE, CODEFIX_NODE),
    (MITIGATION_NODE, NEXT_CANDIDATE_NODE),
    (MITIGATION_NODE, REMEMBERING_NODE),
    (MITIGATION_NODE, END),

    # The loop. An attempt that settled nothing goes back to the proposal node
    # for the next explanation, or back to the Investigator for a wider look -
    # and once neither is left, Code-Fix is the last move Argus has. That is a
    # different road to it than the one above, which a mitigation takes having
    # worked.
    (NEXT_CANDIDATE_NODE, MITIGATION_PROPOSAL_NODE),
    (NEXT_CANDIDATE_NODE, INVESTIGATOR_NODE),
    (NEXT_CANDIDATE_NODE, CODEFIX_NODE),
    (NEXT_CANDIDATE_NODE, END),

    (CODEFIX_NODE, REMEMBERING_NODE),
    (CODEFIX_NODE, END),

    # Remembering comes before the write-up rather than after it, so neither
    # failure can take the other down: this node swallows its own, leaving the
    # postmortem to be written regardless, and a postmortem that raises cannot
    # then cost the next incident what this one learned.
    (REMEMBERING_NODE, POSTMORTEM_NODE),
    (POSTMORTEM_NODE, END)
})

NOTHING_IS_SERVED_HERE = "http://127.0.0.1:1/mcp"


@pytest.mark.unit
def test_every_node_of_the_walk_is_registered() -> None:
    # A node the graph does not know is a node no incident can reach, and the
    # failure shows up as a router returning a key nobody wired.
    Scenario() \
        .given(the_assembled_graph := _a_graph_against_no_database()) \
        .when(lambda: sorted(the_assembled_graph.get_graph().nodes)) \
        .then(_the_nodes_are(sorted([START, END, *EVERY_NODE_IN_THE_WALK])))


@pytest.mark.unit
def test_every_edge_of_the_walk_is_wired() -> None:
    # Asserted whole rather than edge by edge: an edge that should not be there
    # is as wrong as one that is missing, and a test naming only what it
    # expects cannot see the first kind.
    Scenario() \
        .given(the_assembled_graph := _a_graph_against_no_database()) \
        .when(lambda: _the_edges_of(the_assembled_graph)) \
        .then(_the_edges_are(EVERY_EDGE_IN_THE_WALK))


@pytest.mark.unit
def test_the_shortest_possible_walk_costs_what_the_graph_says_it_costs() -> None:
    # Countable by hand off the graph, which is the point of asserting it: one
    # investigation, then the four nodes of a single attempt - proposal, gate,
    # mitigation, next_candidate - then the two that end an incident nobody
    # could fix: codefix, postmortem.
    Scenario() \
        .given(the_shortest_walk := {"max_rounds": 1, "max_candidates": 1}) \
        .when(lambda: recursion_limit(**the_shortest_walk)) \
        .then(_the_limit_is(8))


@pytest.mark.unit
def test_every_extra_candidate_buys_a_whole_attempt() -> None:
    # The loop's traversal budget has to grow with the list, or a verdict with
    # one more explanation than usual ends the incident on a recursion error.
    Scenario() \
        .given(a_walk_of_one := recursion_limit(max_rounds=1, max_candidates=1)) \
        .when(lambda: recursion_limit(max_rounds=1, max_candidates=2)) \
        .then(_the_limit_is(a_walk_of_one + NODES_PER_ATTEMPT))


@pytest.mark.unit
def test_every_extra_round_pays_for_its_investigation_and_its_candidates() -> None:
    # A wider round is one more investigation plus a full list to walk again.
    some_candidates = 3

    Scenario() \
        .given(
            one_round := recursion_limit(max_rounds=1, max_candidates=some_candidates)
        ) \
        .when(lambda: recursion_limit(max_rounds=2, max_candidates=some_candidates)) \
        .then(_the_limit_is(one_round + 1 + NODES_PER_ATTEMPT * some_candidates))


def _a_graph_against_no_database() -> CompiledStateGraph[IncidentState]:
    """The real graph, assembled against connections nothing may open.

    Assembling reaches no database - every collaborator built here is a closure
    over the connections, opened only when a node actually runs - so a source
    that refuses to open is both honest and the assertion: anything that did
    reach for one would fail here rather than silently connect.
    """
    @contextmanager
    def no_connections() -> Generator[psycopg.Connection]:
        raise AssertionError("Assembling the graph must not open a connection.")
        yield  # unreachable, and what makes this a generator

    # No store either: a unit test that held a real `QdrantClient` would open a
    # session to whatever answers on the configured address, and long-term
    # memory is not what a graph's shape is assembled to show.
    return build_graph(MemorySaver(), against(no_connections,
                                              McpClient(NOTHING_IS_SERVED_HERE),
                                              McpClient(NOTHING_IS_SERVED_HERE),
                                              None))



def _the_edges_of(graph: CompiledStateGraph[IncidentState]) -> frozenset[Edge]:
    return frozenset(
        (edge.source, edge.target) for edge in graph.get_graph().edges
    )


def _the_nodes_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(registered: list[str]) -> bool:
        if registered != expected:
            raise AssertionError(
                f"Expected the nodes {expected}, the graph has {registered}"
            )

        return True

    return assertion


def _the_edges_are(expected: frozenset[Edge]) -> Assertion[frozenset[Edge]]:
    """Both directions, reported together. An edge the spec does not have is as
    wrong as one it has and the graph does not, and a failure that named only
    the missing ones would send a reader looking for the wrong mistake."""
    def assertion(wired: frozenset[Edge]) -> bool:
        missing = expected - wired
        unexpected = wired - expected

        if missing or unexpected:
            raise AssertionError(
                f"The graph does not match the spec.\n"
                f"  wired nowhere: {sorted(missing)}\n"
                f"  wired but unspecified: {sorted(unexpected)}"
            )

        return True

    return assertion


def _the_limit_is(expected: int) -> Assertion[int]:
    def assertion(limit: int) -> bool:
        if limit != expected:
            raise AssertionError(f"Expected a limit of {expected}, got {limit}")

        return True

    return assertion
