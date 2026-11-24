"""Which collection a corpus embedded by a model is kept in.

A vector means something only beside vectors the same model made. A collection
named for the corpus alone holds whatever any model ever wrote into it, and a
query embedded by one model is compared with passages embedded by another -
answered, and wrong, with nothing to say so. So the model is part of the name,
and every process that opens a corpus opens it by this name.
"""

from __future__ import annotations

import re

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core.embedding import collection_for

SOME_CORPUS = "target_service_source"
SOME_MODEL = "BAAI/bge-small-en-v1.5"
ANOTHER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Two model names that differ only in characters a collection's name cannot
# carry, and so would be spelled alike if the name were the spelling alone.
A_MODEL_WITH_A_DOT = "some-model-v1.5"
THE_SAME_MODEL_WITH_A_DASH = "some-model-v1-5"

# What a collection's name may hold here: lower-case letters, digits, `-` and
# `_`. Narrower than the store accepts, so a name passes in any store.
A_NAME_ANY_STORE_TAKES = re.compile(r"[a-z0-9_-]+")

# The longest name the store takes (Qdrant refuses one over 255 characters),
# and a recipe far longer than that - an index scoped to many directories.
THE_LONGEST_NAME_A_STORE_TAKES = 255
A_RECIPE_LONGER_THAN_ANY_NAME = SOME_MODEL + " scope=" + ",".join(
    f"services/service_{number}/src" for number in range(100)
)
# The same recipe but for its last directory, which a name cut short to fit
# still has to tell apart.
THE_SAME_RECIPE_BUT_FOR_ITS_END = A_RECIPE_LONGER_THAN_ANY_NAME[:-1] + "x"


@pytest.mark.unit
def test_the_same_corpus_and_model_are_always_the_same_collection() -> None:
    # Every process that opens the corpus works the name out for itself, so a
    # name that varied between two of them would be two corpora.
    Scenario() \
        .given(the_name_once := collection_for(SOME_CORPUS, SOME_MODEL)) \
        .when(lambda: collection_for(SOME_CORPUS, SOME_MODEL)) \
        .then(the_answer_was(the_name_once))


@pytest.mark.unit
def test_another_model_is_another_collection() -> None:
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, ANOTHER_MODEL)) \
        .then(_not(collection_for(SOME_CORPUS, SOME_MODEL)))


@pytest.mark.unit
def test_models_spelled_alike_once_made_a_name_are_still_two_collections() -> None:
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, A_MODEL_WITH_A_DOT)) \
        .then(_not(collection_for(SOME_CORPUS, THE_SAME_MODEL_WITH_A_DASH)))


@pytest.mark.unit
def test_the_collection_is_named_for_its_corpus_first() -> None:
    # Read by a person listing the store's collections, the corpus is what
    # they are looking for.
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, SOME_MODEL)) \
        .then(_starts_with(SOME_CORPUS))


@pytest.mark.unit
def test_a_model_named_with_a_slash_makes_a_name_any_store_takes() -> None:
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, SOME_MODEL)) \
        .then(_holds_only_what_any_store_takes())


@pytest.mark.unit
def test_a_recipe_however_long_makes_a_name_the_store_takes() -> None:
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, A_RECIPE_LONGER_THAN_ANY_NAME)) \
        .then(all_of(
            _no_longer_than(THE_LONGEST_NAME_A_STORE_TAKES),
            _holds_only_what_any_store_takes()
        ))


@pytest.mark.unit
def test_two_long_recipes_differing_only_past_the_cut_are_still_two_collections() -> None:
    Scenario() \
        .when(lambda: collection_for(SOME_CORPUS, A_RECIPE_LONGER_THAN_ANY_NAME)) \
        .then(_not(collection_for(SOME_CORPUS, THE_SAME_RECIPE_BUT_FOR_ITS_END)))


def _no_longer_than(characters: int) -> Assertion[str]:
    def assertion(name: str) -> bool:
        if len(name) > characters:
            raise AssertionError(f"Expected a name of at most [{characters}] characters, got "
                                 f"[{len(name)}]: [{name}].")

        return True

    return assertion


def _not(other: str) -> Assertion[str]:
    def assertion(name: str) -> bool:
        if name == other:
            raise AssertionError(f"Expected a collection other than [{other}], got the same.")

        return True

    return assertion


def _starts_with(corpus: str) -> Assertion[str]:
    def assertion(name: str) -> bool:
        if not name.startswith(corpus):
            raise AssertionError(f"Expected the collection named for [{corpus}] first, got "
                                 f"[{name}].")

        return True

    return assertion


def _holds_only_what_any_store_takes() -> Assertion[str]:
    def assertion(name: str) -> bool:
        if not A_NAME_ANY_STORE_TAKES.fullmatch(name):
            raise AssertionError(f"Expected a name of lower-case letters, digits, '-' and '_' "
                                 f"only, got [{name}].")

        return True

    return assertion
