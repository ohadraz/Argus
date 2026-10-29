"""The layering guard's own rule about the walk, asked of graphs built here.

The rule is the one import-linter cannot hold: no package that walks an
incident may reach a store the fence cannot reach - a vector store, a chat
platform's SDK - except recall's one read. Its failure is silent, like every
guard's: a rule that stopped matching passes every build while the import it
was written against comes back. So each case builds the import graph it is
about, and asks the rule what it makes of it.

Graphs built by hand rather than from the workspace, because grimp builds only
from importable packages and the cases are about imports the workspace must not
have.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario
from grimp import ImportGraph

from scripts.guard_layering import the_chains_to_a_store_the_fence_cannot_reach

THE_WALK = {"orchestrator"}

# The packages that are somebody else's, which the rule is about reaching.
THIRD_PARTIES = {"qdrant_client", "slack_sdk"}


@pytest.mark.unit
def test_a_walk_module_importing_the_vector_store_is_refused() -> None:
    # The import the rule exists for: the walk writing to the store itself,
    # where a write for a run another claim holds is one nothing refuses.
    Scenario() \
        .given(a_graph := _a_graph_with(("orchestrator.walk.assembling", "qdrant_client"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([("orchestrator.walk.assembling", "qdrant_client")]))


@pytest.mark.unit
def test_a_walk_module_reaching_the_vector_store_through_the_writing_side_is_refused() -> None:
    # Indirectly is no better: a walk that calls the keeper writes to the store
    # as surely as one that holds the client.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("orchestrator.walk.assembling", "incident_memory.keeping"),
            ("incident_memory.keeping", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("orchestrator.walk.assembling", "incident_memory.keeping", "qdrant_client")
        ]))


@pytest.mark.unit
def test_a_walk_module_recalling_through_the_reading_side_passes() -> None:
    # Recall is a read, and a read for a lost run changes nothing anybody else
    # holds - which is why the walk keeps it.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("orchestrator.walk.assembling", "incident_memory.recalling"),
            ("incident_memory.recalling", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_way_to_the_writing_side_through_the_reading_side_is_refused() -> None:
    # The exemption is recall's own read of the store, and nothing more. A
    # reading side that came to import the writer would hand the walk the
    # writer through the one door it is allowed - and a rule that waved through
    # every chain passing the reading side would never say so.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("orchestrator.walk.assembling", "incident_memory.recalling"),
            ("incident_memory.recalling", "incident_memory.keeping"),
            ("incident_memory.keeping", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("orchestrator.walk.assembling", "incident_memory.recalling",
             "incident_memory.keeping", "qdrant_client")
        ]))


@pytest.mark.unit
def test_a_walk_module_importing_the_chat_platforms_sdk_is_refused() -> None:
    # A message posted is a change nothing can undo, and the walk tells
    # people through the event log the relay reads - never by posting itself.
    Scenario() \
        .given(a_graph := _a_graph_with(("orchestrator.walk.mitigating", "slack_sdk"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([("orchestrator.walk.mitigating", "slack_sdk")]))


@pytest.mark.unit
def test_a_module_that_walks_nothing_may_import_the_vector_store() -> None:
    # The deliverer is the store's writer by design: it writes outside any run,
    # from rows the fence has already let through.
    Scenario() \
        .given(a_graph := _a_graph_with(("incident_memory.delivering", "qdrant_client"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([]))


def _a_graph_with(*imports: tuple[str, str]) -> ImportGraph:
    """A graph holding these imports and the packages around them, with the
    third parties in it as grimp builds them with externals: one squashed
    module per package."""
    graph = ImportGraph()

    for importer, imported in imports:
        for module in (importer, imported):
            for package in _the_packages_down_to(module):
                if package not in graph.modules:
                    graph.add_module(package, is_squashed=package in THIRD_PARTIES)

        graph.add_import(importer=importer, imported=imported)

    return graph


def _the_packages_down_to(module: str) -> list[str]:
    """`a`, `a.b` and `a.b.c` for `a.b.c`: a module is in a graph with every
    package it sits in, which is what lets a rule ask about a package whole."""
    parts = module.split(".")

    return [".".join(parts[:depth]) for depth in range(1, len(parts) + 1)]


def _these_are_refused(expected: list[tuple[str, ...]]) -> Assertion[list[tuple[str, ...]]]:
    def assertion(refused: list[tuple[str, ...]]) -> bool:
        if refused != expected:
            raise AssertionError(f"Expected the chains {expected} refused, got {refused}.")

        return True

    return assertion
