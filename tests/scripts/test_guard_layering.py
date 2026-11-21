"""The layering guard's own rules that import-linter cannot hold, asked of
graphs and sources built here.

Three rules. No package that walks an incident may reach a store the fence
cannot reach - a vector store, a chat platform's SDK - except recall's one read.
No module but a vendor's adapter may import that vendor's SDK. Both are about
third parties, which import-linter sees only with a setting that is global and
turns every other contract against the standard library. And no module outside
the walk and the kernel may make an admission: the Mitigator imports the
autonomy policy for the type its write accepts, and import-linter cannot allow
the type and forbid `admit` beside it. Their failure is silent, like every
guard's: a rule that stopped matching passes every build while the import it
was written against comes back. So each case builds the graph or the source it
is about, and asks the rule what it makes of it.

Built by hand rather than read from the workspace, because the cases are about
imports the workspace must not have.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario
from grimp import ImportGraph

from scripts.guard_layering import (
    the_admissions_made_outside_the_walk,
    the_chains_to_a_store_the_fence_cannot_reach,
    the_vendors_spoken_past_their_adapter,
)

THE_WALK = {"orchestrator"}

# The packages that are somebody else's, which the rule is about reaching.
THIRD_PARTIES = {"qdrant_client", "slack_sdk"}


@pytest.mark.unit
def test_a_walk_module_importing_the_vector_store_is_refused() -> None:
    # The import the rule exists for: the walk writing to the store itself,
    # where a write for a run another claim holds is one nothing refuses.
    Scenario() \
        .given(a_graph := _a_graph_with(("orchestrator.assembling", "qdrant_client"))) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([("orchestrator.assembling", "qdrant_client")]))


@pytest.mark.unit
def test_a_walk_module_reaching_the_vector_store_through_the_writing_side_is_refused() -> None:
    # Indirectly is no better: a walk that builds the writing side of the
    # adapter writes to the store as surely as one that holds the client.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("orchestrator.assembling", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("orchestrator.assembling", "vector_store_qdrant.indexing", "qdrant_client")
        ]))


@pytest.mark.unit
def test_a_walk_module_recalling_through_the_reading_side_passes() -> None:
    # Recall is a read, and a read for a lost run changes nothing anybody else
    # holds - which is why the walk's wiring may build the adapter's reading side.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("orchestrator.assembling", "vector_store_qdrant.searching"),
            ("vector_store_qdrant.searching", "qdrant_client")
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
            ("orchestrator.assembling", "vector_store_qdrant.searching"),
            ("vector_store_qdrant.searching", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([
            ("orchestrator.assembling", "vector_store_qdrant.searching",
             "vector_store_qdrant.indexing", "qdrant_client")
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
        .given(a_graph := _a_graph_with(
            ("incident_memory.delivering", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_chains_to_a_store_the_fence_cannot_reach(a_graph, THE_WALK)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_module_importing_a_vendors_sdk_past_its_adapter_is_refused() -> None:
    # Typing a store by the vendor's client again, which is how the port came
    # to be missing in the first place.
    Scenario() \
        .given(a_graph := _a_graph_with(("repository_index.store", "qdrant_client"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("repository_index.store", "qdrant_client")]))


@pytest.mark.unit
def test_the_vendors_adapter_importing_its_sdk_passes() -> None:
    # The adapter is the one place the vendor is spoken: both of its sides.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("vector_store_qdrant.searching", "qdrant_client"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_module_reaching_a_vendors_sdk_through_its_adapter_passes() -> None:
    # A process's wiring builds the adapter, and the adapter speaks the vendor:
    # that is the port working, not reached past.
    Scenario() \
        .given(a_graph := _a_graph_with(
            ("incident_memory.delivering", "vector_store_qdrant.indexing"),
            ("vector_store_qdrant.indexing", "qdrant_client")
        )) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


@pytest.mark.unit
def test_a_package_named_like_the_adapter_is_not_the_adapter() -> None:
    # The allowance is the adapter's package and what is inside it, never a
    # package whose name merely begins the same way.
    Scenario() \
        .given(a_graph := _a_graph_with(("vector_store_qdrant_tools.export", "qdrant_client"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("vector_store_qdrant_tools.export", "qdrant_client")]))


@pytest.mark.unit
def test_the_model_vendors_sdk_named_past_its_adapter_is_refused() -> None:
    # How the port came to be missing: the factory named the SDK's client in
    # its own signature, so every caller of it held Anthropic's type.
    Scenario() \
        .given(a_graph := _a_graph_with(("core.llm.building", "anthropic"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([("core.llm.building", "anthropic")]))


@pytest.mark.unit
def test_the_model_vendors_adapter_importing_its_sdk_passes() -> None:
    # One module rather than a package, and the one place Anthropic is spoken.
    Scenario() \
        .given(a_graph := _a_graph_with(("core.llm.adapters.anthropic_adapter", "anthropic"))) \
        .when(lambda: the_vendors_spoken_past_their_adapter(a_graph)) \
        .then(_these_are_refused([]))


# The Mitigator's write, which accepts an admission and must never make one.
THE_MITIGATOR_S_WRITE = "mitigation.trying"


@pytest.mark.unit
def test_the_mitigator_naming_the_admission_it_accepts_passes() -> None:
    # The import the policy's narrow door exists for: the write names the type
    # it accepts, which is what makes an action nobody admitted a type error.
    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(
            "from core.autonomy import Admitted")}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([]))


@pytest.mark.unit
@pytest.mark.parametrize("reaching", [
    pytest.param(["from core.autonomy import admit"], id="imported"),
    pytest.param(["from core.autonomy import Admitted, admit as allowed"], id="renamed"),
    pytest.param(["from core.autonomy import *"], id="everything"),
    pytest.param(["from core.autonomy import _ADMISSION"], id="the-key"),
    pytest.param(["def taking() -> None:", "    from core.autonomy import admit"],
                 id="deferred")
])
def test_the_mitigator_importing_what_makes_an_admission_is_refused(reaching: list[str]) -> None:
    # `admit` takes the reach it judges by from its caller, so a Mitigator that
    # could call it would admit any declared kind wherever its action was
    # aimed. Refused however it is spelled, and at the line that spells it.
    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(*reaching)}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([(THE_MITIGATOR_S_WRITE, len(reaching))]))


@pytest.mark.unit
@pytest.mark.parametrize("binding", [
    pytest.param(("import core.autonomy", "core.autonomy"), id="by-path"),
    pytest.param(("import core.autonomy as policy", "policy"), id="aliased"),
    pytest.param(("from core import autonomy", "autonomy"), id="from-the-kernel"),
    pytest.param(("import core", "core.autonomy"), id="through-the-kernel"),
    # Any `import core.<x>` binds `core` itself, and the policy is reachable
    # through it once anything has loaded it - which the worker always has.
    pytest.param(("import core.models", "core.autonomy"), id="through-another-door")
])
def test_the_mitigator_referring_to_admit_on_the_policy_module_is_refused(
    binding: tuple[str, str]
) -> None:
    # The import alone names no `admit`; a reference to it does, on the line
    # after it - called or not, since a reference is what a call is made with.
    imported, referred_to_as = binding
    lines = [imported, f"{referred_to_as}.admit"]

    Scenario() \
        .given(sources := {THE_MITIGATOR_S_WRITE: _a_module_reading(*lines)}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([(THE_MITIGATOR_S_WRITE, len(lines))]))


@pytest.mark.unit
@pytest.mark.parametrize("module", ["orchestrator.walk.mitigating", "core.autonomy"])
def test_the_walk_and_the_kernel_may_make_an_admission(module: str) -> None:
    # The walk asks the policy, at the gate and again as the action is taken;
    # the kernel is where `admit` is written.
    Scenario() \
        .given(sources := {module: _a_module_reading("from core.autonomy import admit")}) \
        .when(lambda: the_admissions_made_outside_the_walk(sources)) \
        .then(_these_admissions_are_refused([]))


def _a_module_reading(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _these_admissions_are_refused(expected: list[tuple[str, int]]
                                  ) -> Assertion[list[tuple[str, int]]]:
    def assertion(refused: list[tuple[str, int]]) -> bool:
        if refused != expected:
            raise AssertionError(
                f"Expected the admissions at {expected} refused, got {refused}."
            )

        return True

    return assertion


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
