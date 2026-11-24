"""What an index of the repository is built with.

Everything the stored passages are derived from apart from the commit: the
model that embedded them, the bounds a file is cut by, and the directories that
are the service. A change to any one makes other passages, so each has to make
another recipe - one left out is a collection built two ways, answering from
both, and a mark calling it current.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, the_answer_was
from repository_index.recipe import built_with

SOME_MODEL = "BAAI/bge-small-en-v1.5"
ANOTHER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
SOME_SCOPE = "src/shop"
A_WIDER_SCOPE = "src/shop,src/payments"
# The wider scope again, its directories in the other order and spaced as a
# person writes a list - the same files, read as the index reads them.
THE_WIDER_SCOPE_WRITTEN_ANOTHER_WAY = "src/payments, src/shop"
SOME_MAX_LINES = 60
OTHER_MAX_LINES = 80
SOME_OVERLAP = 10
OTHER_OVERLAP = 20


@pytest.mark.unit
def test_the_same_settings_are_always_the_same_recipe() -> None:
    # The catch-up loop and the read server each work the recipe out for
    # themselves, from the same settings, and have to arrive at one collection.
    Scenario() \
        .when(lambda: built_with(embedding_model=SOME_MODEL,
                                 service_source_paths=SOME_SCOPE,
                                 max_lines=SOME_MAX_LINES,
                                 overlap=SOME_OVERLAP)) \
        .then(the_answer_was(_the_recipe_of_some_settings()))


@pytest.mark.unit
def test_another_embedding_model_is_another_recipe() -> None:
    Scenario() \
        .when(lambda: built_with(embedding_model=ANOTHER_MODEL,
                                 service_source_paths=SOME_SCOPE,
                                 max_lines=SOME_MAX_LINES,
                                 overlap=SOME_OVERLAP)) \
        .then(_not(_the_recipe_of_some_settings()))


@pytest.mark.unit
def test_cutting_a_file_by_more_lines_is_another_recipe() -> None:
    Scenario() \
        .when(lambda: built_with(embedding_model=SOME_MODEL,
                                 service_source_paths=SOME_SCOPE,
                                 max_lines=OTHER_MAX_LINES,
                                 overlap=SOME_OVERLAP)) \
        .then(_not(_the_recipe_of_some_settings()))


@pytest.mark.unit
def test_repeating_more_of_each_window_is_another_recipe() -> None:
    Scenario() \
        .when(lambda: built_with(embedding_model=SOME_MODEL,
                                 service_source_paths=SOME_SCOPE,
                                 max_lines=SOME_MAX_LINES,
                                 overlap=OTHER_OVERLAP)) \
        .then(_not(_the_recipe_of_some_settings()))


@pytest.mark.unit
def test_a_wider_scope_is_another_recipe() -> None:
    # Left out, a wider scope would find the index current, and the files it
    # brought in would be cut only as each one next changed.
    Scenario() \
        .when(lambda: built_with(embedding_model=SOME_MODEL,
                                 service_source_paths=A_WIDER_SCOPE,
                                 max_lines=SOME_MAX_LINES,
                                 overlap=SOME_OVERLAP)) \
        .then(_not(_the_recipe_of_some_settings()))


@pytest.mark.unit
def test_the_same_scope_written_in_another_order_is_the_same_recipe() -> None:
    # Spelled as written, it would be another collection, and a whole index
    # built again for the same files.
    Scenario() \
        .when(lambda: built_with(embedding_model=SOME_MODEL,
                                 service_source_paths=THE_WIDER_SCOPE_WRITTEN_ANOTHER_WAY,
                                 max_lines=SOME_MAX_LINES,
                                 overlap=SOME_OVERLAP)) \
        .then(the_answer_was(built_with(embedding_model=SOME_MODEL,
                                        service_source_paths=A_WIDER_SCOPE,
                                        max_lines=SOME_MAX_LINES,
                                        overlap=SOME_OVERLAP)))


def _the_recipe_of_some_settings() -> str:
    """What the settings every case varies one of from make, to compare with."""
    return built_with(embedding_model=SOME_MODEL,
                      service_source_paths=SOME_SCOPE,
                      max_lines=SOME_MAX_LINES,
                      overlap=SOME_OVERLAP)


def _not(other: str) -> Assertion[str]:
    def assertion(recipe: str) -> bool:
        if recipe == other:
            raise AssertionError(f"Expected a recipe other than [{other}], got the same.")

        return True

    return assertion
