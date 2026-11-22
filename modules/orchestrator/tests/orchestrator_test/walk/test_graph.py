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

import dataclasses
from collections.abc import Callable
from typing import Any, NoReturn

import pytest
from argus_testkit import Assertion, Scenario
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START
from langgraph.graph.state import CompiledStateGraph
from orchestrator.walk.collaborators import Collaborators
from orchestrator.walk.graph import (
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    SYNOPSIS_NODE,
    TIER_GATE_NODE,
    build_graph,
    recursion_limit,
)
from orchestrator.walk.state import IncidentState

type Edge = tuple[str, str]

NODES_PER_ATTEMPT = 4
NODES_PER_INVESTIGATION = len([INVESTIGATOR_NODE])

EVERY_NODE_IN_THE_WALK = [
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    SYNOPSIS_NODE,
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
    # A round that named only what the walk had already tried has spent the
    # list, and goes to Code-Fix as a walk out of candidates does.
    (INVESTIGATOR_NODE, CODEFIX_NODE),
    (INVESTIGATOR_NODE, REMEMBERING_NODE),
    (INVESTIGATOR_NODE, END),

    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    (MITIGATION_PROPOSAL_NODE, TIER_GATE_NODE),

    (TIER_GATE_NODE, MITIGATION_NODE),
    (TIER_GATE_NODE, NEXT_CANDIDATE_NODE),
    # An action the gate declined because nothing could confirm it: the
    # mitigation phase is over and the fault is still in the code.
    (TIER_GATE_NODE, CODEFIX_NODE),
    # A person reported the incident resolved: past anything still to try, on
    # to be remembered and written up. Every router carries the edge; the
    # investigator, mitigation and Code-Fix already had it.
    (TIER_GATE_NODE, REMEMBERING_NODE),
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
    (NEXT_CANDIDATE_NODE, REMEMBERING_NODE),
    (NEXT_CANDIDATE_NODE, END),

    (CODEFIX_NODE, REMEMBERING_NODE),
    (CODEFIX_NODE, END),

    # Remembering comes before the write-up rather than after it, so neither
    # failure can take the other down: this node swallows its own, leaving the
    # postmortem to be written regardless, and a postmortem that raises cannot
    # then cost the next incident what this one learned.
    (REMEMBERING_NODE, POSTMORTEM_NODE),
    # The synopsis is written from the stored postmortem, so after it - and
    # as a step of its own, so a synopsis that fails cannot have the
    # postmortem written again.
    (POSTMORTEM_NODE, SYNOPSIS_NODE),
    (SYNOPSIS_NODE, END)
})

# The two collaborators that are numbers rather than calls, which no case here
# reads: the graph's shape does not depend on either.
DONT_CARE_ROUNDS = 3
DONT_CARE_ATTEMPTS = 2


@pytest.mark.unit
def test_every_node_of_the_walk_is_registered() -> None:
    # A node the graph does not know is a node no incident can reach, and the
    # failure shows up as a router returning a key nobody wired.
    Scenario() \
        .given(an_assembled_graph := _a_graph_over_stand_ins()) \
        .when(lambda: sorted(an_assembled_graph.get_graph().nodes)) \
        .then(_the_nodes_are(sorted([START, END, *EVERY_NODE_IN_THE_WALK])))


@pytest.mark.unit
def test_every_edge_of_the_walk_is_wired() -> None:
    # Asserted whole rather than edge by edge: an edge that should not be there
    # is as wrong as one that is missing, and a test naming only what it
    # expects cannot see the first kind.
    Scenario() \
        .given(an_assembled_graph := _a_graph_over_stand_ins()) \
        .when(lambda: _the_edges_of(an_assembled_graph)) \
        .then(_the_edges_are(EVERY_EDGE_IN_THE_WALK))


@pytest.mark.unit
def test_the_shortest_possible_walk_costs_what_the_graph_says_it_costs() -> None:
    # Countable by hand off the graph, which is the point of asserting it: one
    # investigation, then the four nodes of a single attempt - proposal, gate,
    # mitigation, next_candidate - then the four that end an incident nobody
    # could fix: codefix, remembering, postmortem, synopsis.
    the_fewest_rounds = 1
    the_fewest_candidates = 1
    the_investigation = [INVESTIGATOR_NODE]
    the_ending_nobody_could_fix = [CODEFIX_NODE, REMEMBERING_NODE, POSTMORTEM_NODE,
                                   SYNOPSIS_NODE]

    Scenario() \
        .given(a_shortest_walk := {"max_rounds": the_fewest_rounds,
                                   "max_candidates": the_fewest_candidates}) \
        .when(lambda: recursion_limit(**a_shortest_walk)) \
        .then(_the_limit_is(len(the_investigation) + NODES_PER_ATTEMPT
                            + len(the_ending_nobody_could_fix)))


@pytest.mark.unit
def test_every_extra_candidate_buys_a_whole_attempt() -> None:
    # The loop's traversal budget has to grow with the list, or a verdict with
    # one more explanation than usual ends the incident on a recursion error.
    # One round, because each round walks the list again.
    one_round = 1
    some_candidates = 1

    Scenario() \
        .given(
            a_walk_of_one := recursion_limit(max_rounds=one_round,
                                             max_candidates=some_candidates)
        ) \
        .when(lambda: recursion_limit(max_rounds=one_round,
                                      max_candidates=some_candidates + 1)) \
        .then(_the_limit_is(a_walk_of_one + NODES_PER_ATTEMPT))


@pytest.mark.unit
def test_every_extra_round_pays_for_its_investigation_and_its_candidates() -> None:
    # A wider round is one more investigation plus a full list to walk again.
    one_round = 1
    some_candidates = 3

    Scenario() \
        .given(
            a_walk_of_one_round := recursion_limit(max_rounds=one_round,
                                                   max_candidates=some_candidates)
        ) \
        .when(lambda: recursion_limit(max_rounds=one_round + 1,
                                      max_candidates=some_candidates)) \
        .then(_the_limit_is(a_walk_of_one_round + NODES_PER_INVESTIGATION
                            + NODES_PER_ATTEMPT * some_candidates))


def _a_graph_over_stand_ins() -> CompiledStateGraph[IncidentState]:
    """The real graph, its nodes handed collaborators that are never asked.

    Its shape is decided as it is built, by the nodes and the routers, and no
    node asks its collaborators anything until a walk runs one - so each stands
    in as a call that fails, naming itself, if it is ever made. What a
    deployment hands the graph, and that assembling it reaches nothing, is the
    worker's root's to show (`apps_test.worker.test_assembling`).
    """
    stood_in: dict[str, Any] = {
        field.name: _never_asked(field.name) for field in dataclasses.fields(Collaborators)
    }

    return build_graph(MemorySaver(), Collaborators(**(stood_in | {
        "max_rounds": DONT_CARE_ROUNDS,
        "attempts_per_subject": DONT_CARE_ATTEMPTS
    })))


def _never_asked(collaborator: str) -> Callable[..., NoReturn]:
    def asked(*dont_care_args: object, **dont_care_keywords: object) -> NoReturn:
        raise AssertionError(f"Building the graph must not ask [{collaborator}] anything.")

    return asked


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
