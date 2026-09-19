"""The model that turns passages into vectors.

The one collaborator every other test here replaces with a double, which is
exactly why it needs a suite of its own: a seam nothing ever exercises is a seam
that works until the day it is used.

It runs in this process. No key, no network, no bill - which is why it was
chosen, and the reasons are worth stating plainly because retrieval quality is
not among them. A hosted model trained on code would rank better than a small
general-purpose English one; what this buys instead is that indexing costs
nothing, that an incident never waits on a vendor, and that nothing external has
to be faked for a suite to run.

Marked `component` because it loads a model. Nothing here is fast, and nothing
here should be asked of a unit test.

The last test is the only one that asks whether the model is any good, and it
asks the smallest useful version of the question: does code that does what a
description describes come out nearer than code that does something else. That
is the whole claim retrieval by meaning rests on, and if it fails here the
decision to embed locally is the thing to revisit.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from code_index.embedding import an_embedder

SOME_TEXT = "def summary() -> None:\n    return None\n"
ANOTHER_TEXT = "class Accounts:\n    pass\n"

# What the description is about, and the two passages it must choose between.
A_DESCRIPTION_OF_DIVIDING_BY_ZERO = "divides by a count that can be zero"

SOME_CODE_THAT_DIVIDES = (
    "def average_spend(purchases):\n"
    "    return total(purchases) / len(purchases)\n"
)
SOME_CODE_ABOUT_SOMETHING_ELSE = (
    "def render_footer(request):\n"
    "    return template('footer.html')\n"
)


@pytest.mark.component
def test_one_vector_comes_back_for_each_text() -> None:
    # The contract the whole pairing rests on. A model that answered a short
    # batch would have `points_of` drop the last chunks, and `strict` on that
    # zip is what turns it into a failure rather than a silence.
    Scenario() \
        .given(some_texts := [SOME_TEXT, ANOTHER_TEXT]) \
        .when(lambda: an_embedder()(some_texts)) \
        .then(_exactly_this_many_vectors(2))


@pytest.mark.component
def test_every_vector_is_the_same_width() -> None:
    # A collection is created with one width and refuses anything else, so a
    # batch of uneven vectors is a store that rejects half a file.
    Scenario() \
        .given(some_texts := [SOME_TEXT, ANOTHER_TEXT, SOME_CODE_THAT_DIVIDES]) \
        .when(lambda: an_embedder()(some_texts)) \
        .then(_every_vector_is_the_same_width())


@pytest.mark.component
def test_the_same_text_always_embeds_to_the_same_vector() -> None:
    # What makes an index reproducible. A model that answered differently twice
    # would have every re-index rewrite every point, and a benchmark comparing
    # two runs would be measuring the model's mood.
    first = an_embedder()([SOME_TEXT])

    Scenario() \
        .when(lambda: an_embedder()([SOME_TEXT])) \
        .then(_the_vectors_are_those_of(first))


@pytest.mark.component
def test_code_is_nearer_a_description_of_what_it_does_than_unrelated_code() -> None:
    # The claim retrieval by meaning rests on, at its smallest. Neither passage
    # contains the words of the description - one says `len(purchases)` and the
    # other says nothing about counting at all - so a substring search would
    # find neither, which is the case this whole channel exists for.
    Scenario() \
        .given(
            some_texts := [
                A_DESCRIPTION_OF_DIVIDING_BY_ZERO,
                SOME_CODE_THAT_DIVIDES,
                SOME_CODE_ABOUT_SOMETHING_ELSE
            ]
        ) \
        .when(lambda: an_embedder()(some_texts)) \
        .then(_the_second_is_nearer_the_first_than_the_third_is())


@pytest.mark.component
def test_a_model_nobody_has_is_refused_rather_than_quietly_replaced() -> None:
    # What makes `CODE_INDEX_EMBEDDING_MODEL` a setting rather than a comment:
    # the name is carried to the library and used. A named model that fell back
    # to the built-in one would leave a benchmark comparing two models that were
    # the same model, and every figure it produced would be about nothing.
    Scenario() \
        .given(a_model_nobody_has := "not-a-model/does-not-exist") \
        .when(
            attempting(lambda: an_embedder(a_model_nobody_has)([SOME_TEXT]))
        ) \
        .then(an_error_was_raised(ValueError))


def _exactly_this_many_vectors(expected: int) -> Assertion[list[list[float]]]:
    def exactly_this_many_vectors(vectors: list[list[float]]) -> bool:
        if len(vectors) != expected:
            raise AssertionError(
                f"Expected [{expected}] vectors, and [{len(vectors)}] "
                f"came back."
            )

        return True

    return exactly_this_many_vectors


def _every_vector_is_the_same_width() -> Assertion[list[list[float]]]:
    def every_vector_is_the_same_width(vectors: list[list[float]]) -> bool:
        widths = {len(vector) for vector in vectors}

        if len(widths) != 1:
            raise AssertionError(
                f"Expected every vector to be the same width, "
                f"and they ran {sorted(widths)}."
            )

        return True

    return every_vector_is_the_same_width


def _the_vectors_are_those_of(
    earlier: list[list[float]]
) -> Assertion[list[list[float]]]:
    def the_vectors_are_those_of(vectors: list[list[float]]) -> bool:
        if vectors != earlier:
            raise AssertionError(
                "Expected the same text to embed to the same vector twice, "
                "and the two runs disagreed."
            )

        return True

    return the_vectors_are_those_of


def _the_second_is_nearer_the_first_than_the_third_is(
) -> Assertion[list[list[float]]]:
    """That the description is nearer the code that does it than the code that does not.

    Cosine, because that is what the collection is created with - asserting
    nearness by any other measure would be asserting something the store does
    not do.
    """
    def the_second_is_nearer(vectors: list[list[float]]) -> bool:
        description, does_it, does_not = vectors
        near = _cosine(description, does_it)
        far = _cosine(description, does_not)

        if near <= far:
            raise AssertionError(
                f"Expected code that divides by a count to be nearer "
                f"[{A_DESCRIPTION_OF_DIVIDING_BY_ZERO}] than unrelated code is. "
                f"It scored [{near:.4f}] against the other's [{far:.4f}]."
            )

        return True

    return the_second_is_nearer


def _cosine(one: list[float], another: list[float]) -> float:
    dot = sum(a * b for a, b in zip(one, another, strict=True))
    length = (sum(a * a for a in one) ** 0.5) * (sum(b * b for b in another) ** 0.5)

    return dot / length if length else 0.0
