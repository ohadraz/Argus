"""Turning a repository's files into the points that go into the store.

The step between cutting and storing. Files in, points out: each point one
chunk, the vector that chunk embedded to, and an id derived from what it says.

Two things are decided here and neither is visible from outside once wrong.

A file is embedded in one call rather than a chunk at a time. Not for the round
trips - the embedder runs in this process and there are none - but because
batch inference is several times faster than the same work done one text at a
time. Per file rather than per repository, so what is held in memory at once is
one file's chunks and not a whole codebase's.

An id is a hash of the path and the chunk's text, so the same passage has the
same id wherever it sits in the file. That is what lets a re-index ask the store
what it already holds and embed only what actually changed - a function that
moved because something above it grew is not a function that needs embedding
again. An id keyed on position could not tell the two apart, and a random id
could not tell anything apart at all.

The embedder is injected. It is the one collaborator here that would otherwise
load a model, and a unit test that loads a model is a unit test nobody runs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of
from code_index.indexing import (
    Candidate,
    Embedder,
    Point,
    candidates_for,
    ids_no_longer_present,
    points_for,
)

SOME_DIRECTORY = "src/shop"
SOME_TEXT_PATH = f"{SOME_DIRECTORY}/notes.txt"
SOME_PYTHON_PATH = f"{SOME_DIRECTORY}/summary.py"
SOME_PATH_OUT_OF_SCOPE = "elsewhere/scenarios.py"

# Two top-level functions, so the file is two chunks - and of different lengths,
# so a vector derived from the text tells them apart. A pair that embedded
# identically would let a misordered batch pass unnoticed.
SOME_SOURCE_OF_TWO_CHUNKS = "\n".join([
    "def first() -> None:",
    "    return None",
    "",
    "",
    "def second_one_that_is_longer() -> None:",
    "    return None"
])

# The same file after something was added above it. `first` is word for word
# what it was and sits two lines further down.
THE_SAME_SOURCE_PUSHED_DOWN = "\n".join([
    "# a note somebody added at the top",
    "",
    "def first() -> None:",
    "    return None",
    "",
    "",
    "def second_one_that_is_longer() -> None:",
    "    return None"
])

SOME_TEXT = "a line of prose that is not code at all"

# A file with no structure this module understands, long enough to be cut more
# than one way - which is what makes the bounds observable at all.
SOME_PROSE_OF_TWELVE_LINES = "\n".join(f"line {number}" for number in range(1, 13))


@pytest.mark.unit
def test_every_chunk_of_a_file_in_scope_becomes_a_point() -> None:
    Scenario() \
        .given(
            some_files := {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS},
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(
            lambda: points_for(
                some_files, the_service_lives_in, _an_embedder()
            )
        ) \
        .then(
            all_of(
                _exactly_this_many_points(2),
                _every_point_names(SOME_PYTHON_PATH)
            )
        )


@pytest.mark.unit
def test_a_file_outside_the_scope_contributes_nothing() -> None:
    # The harness that stages incidents, kept out of the index for the reason it
    # is kept out of the substring channel: an agent that retrieves it is
    # retrieving how its own incidents are made.
    Scenario() \
        .given(
            some_files := {
                SOME_TEXT_PATH: SOME_TEXT,
                SOME_PATH_OUT_OF_SCOPE: SOME_SOURCE_OF_TWO_CHUNKS
            },
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(
            lambda: points_for(
                some_files, the_service_lives_in, _an_embedder()
            )
        ) \
        .then(
            all_of(
                _exactly_this_many_points(1),
                _no_point_names(SOME_PATH_OUT_OF_SCOPE)
            )
        )


@pytest.mark.unit
def test_a_file_is_embedded_in_one_call_however_many_chunks_it_has() -> None:
    # Batch inference is several times faster than the same texts one at a
    # time, and the shape of the call is what decides whether it happens - it
    # is not something to retrofit once the repository is large.
    embed = _an_embedder()

    Scenario() \
        .given(
            some_files := {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS},
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(lambda: points_for(some_files, the_service_lives_in, embed)) \
        .then(
            all_of(
                _the_embedder_was_called(embed, times=1),
                _exactly_this_many_points(2)
            )
        )


@pytest.mark.unit
def test_each_file_is_embedded_on_its_own() -> None:
    # The other half of the batching decision, and the reason it is not one
    # call for everything: what is held in memory at once is one file's chunks
    # and its vectors, whatever size the repository grows to.
    embed = _an_embedder()

    Scenario() \
        .given(
            some_files := {
                SOME_TEXT_PATH: SOME_TEXT,
                SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS
            },
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(lambda: points_for(some_files, the_service_lives_in, embed)) \
        .then(
            all_of(
                _the_embedder_was_called(embed, times=2),
                _exactly_this_many_points(3)
            )
        )


@pytest.mark.unit
def test_each_point_carries_the_vector_returned_for_its_own_text() -> None:
    # A batch of texts goes out and a batch of vectors comes back, and nothing
    # says the two line up except the code that pairs them. A chunk wearing its
    # neighbour's vector is retrieved for the wrong query and looks perfectly
    # well from outside.
    Scenario() \
        .given(
            some_files := {
                SOME_TEXT_PATH: SOME_TEXT,
                SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS
            },
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(
            lambda: points_for(
                some_files, the_service_lives_in, _an_embedder()
            )
        ) \
        .then(_every_point_embedded_its_own_text())


@pytest.mark.unit
def test_a_chunk_that_only_moved_keeps_its_id() -> None:
    # What the id is for. A function pushed down the file because something was
    # added above it has not changed, and a re-index that can see that skips
    # embedding it. Keyed on position, every chunk below an edit would look new.
    before = points_for(
        {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS},
        SOME_DIRECTORY,
        _an_embedder()
    )

    Scenario() \
        .given(
            the_file_after_an_insert := {
                SOME_PYTHON_PATH: THE_SAME_SOURCE_PUSHED_DOWN
            }
        ) \
        .when(
            lambda: points_for(
                the_file_after_an_insert, SOME_DIRECTORY, _an_embedder()
            )
        ) \
        .then(_it_still_holds_the_ids_of(before))


@pytest.mark.unit
def test_two_chunks_of_one_file_do_not_share_an_id() -> None:
    # The other half of the same rule. Ids that collided within a file would
    # have the second chunk overwrite the first, and a file would be indexed one
    # passage deep however long it is.
    Scenario() \
        .given(
            some_files := {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS}
        ) \
        .when(
            lambda: points_for(
                some_files, SOME_DIRECTORY, _an_embedder()
            )
        ) \
        .then(_every_id_is_distinct())


@pytest.mark.unit
def test_the_same_text_in_two_files_is_two_points() -> None:
    # The path is part of the id. Two services that both declare an identical
    # helper are two places a fix might belong, and an id that could not tell
    # them apart would index one and silently lose the other.
    some_shared_helper = "def helper() -> None:\n    return None"

    Scenario() \
        .given(
            some_files := {
                f"{SOME_DIRECTORY}/one.py": some_shared_helper,
                f"{SOME_DIRECTORY}/two.py": some_shared_helper
            }
        ) \
        .when(
            lambda: points_for(
                some_files, SOME_DIRECTORY, _an_embedder()
            )
        ) \
        .then(
            all_of(
                _exactly_this_many_points(2),
                _every_id_is_distinct()
            )
        )


@pytest.mark.unit
def test_a_repository_with_nothing_in_scope_is_not_embedded_at_all() -> None:
    # Scope before embedding rather than after. Embedding a file and then
    # discarding it costs the same as keeping it and is harder to notice.
    embed = _an_embedder()

    Scenario() \
        .given(
            some_files := {SOME_PATH_OUT_OF_SCOPE: SOME_SOURCE_OF_TWO_CHUNKS},
            the_service_lives_in := SOME_DIRECTORY
        ) \
        .when(lambda: points_for(some_files, the_service_lives_in, embed)) \
        .then(
            all_of(
                _exactly_this_many_points(0),
                _the_embedder_was_called(embed, times=0)
            )
        )


@pytest.mark.unit
def test_a_chunk_the_store_already_holds_is_not_embedded_again() -> None:
    # The whole reason an id is a hash of the text. The store is asked what it
    # holds before anything is embedded, so a function that only moved costs
    # nothing to re-index.
    held = _the_ids_of(
        points_for({SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS}, SOME_DIRECTORY,
                   _an_embedder())
    )
    embed = _an_embedder()

    Scenario() \
        .given(
            the_file_after_an_insert := {
                SOME_PYTHON_PATH: THE_SAME_SOURCE_PUSHED_DOWN
            }
        ) \
        .when(
            lambda: points_for(
                the_file_after_an_insert, SOME_DIRECTORY, embed, held_ids=held
            )
        ) \
        .then(
            all_of(
                _exactly_this_many_points(1),
                _no_point_carries_an_id_in(held)
            )
        )


@pytest.mark.unit
def test_a_file_wholly_unchanged_is_not_embedded_at_all() -> None:
    # The common case on a push that touched one file: every other file is
    # word for word what it was, and must cost nothing.
    some_files = {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS}
    held = _the_ids_of(points_for(some_files, SOME_DIRECTORY, _an_embedder()))
    embed = _an_embedder()

    Scenario() \
        .when(
            lambda: points_for(
                some_files, SOME_DIRECTORY, embed, held_ids=held
            )
        ) \
        .then(
            all_of(
                _exactly_this_many_points(0),
                _the_embedder_was_called(embed, times=0)
            )
        )


@pytest.mark.unit
def test_an_empty_store_means_everything_is_embedded() -> None:
    # Backfill is not a second code path. It is this one, reconciling from a
    # store that holds nothing.
    embed = _an_embedder()

    Scenario() \
        .given(
            some_files := {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS},
            the_store_holds_nothing := frozenset[str]()
        ) \
        .when(
            lambda: points_for(
                some_files, SOME_DIRECTORY, embed, held_ids=the_store_holds_nothing
            )
        ) \
        .then(_exactly_this_many_points(2))


@pytest.mark.unit
def test_an_id_the_file_no_longer_has_is_named_for_forgetting() -> None:
    # The delete side, and why determinism alone is not enough: a function that
    # was edited or removed leaves a point behind that matches nothing in the
    # file any more, and retrieval would go on answering with it.
    some_files = {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS}
    held = _the_ids_of(points_for(some_files, SOME_DIRECTORY, _an_embedder()))
    a_forgotten_id = "00000000-0000-0000-0000-000000000000"

    Scenario() \
        .given(the_store_also_holds := held | {a_forgotten_id}) \
        .when(
            lambda: ids_no_longer_present(
                some_files, SOME_DIRECTORY, the_store_also_holds
            )
        ) \
        .then(_exactly_these_ids([a_forgotten_id]))


@pytest.mark.unit
def test_an_id_the_file_still_has_is_not_named_for_forgetting() -> None:
    some_files = {SOME_PYTHON_PATH: SOME_SOURCE_OF_TWO_CHUNKS}
    held = _the_ids_of(points_for(some_files, SOME_DIRECTORY, _an_embedder()))

    Scenario() \
        .when(
            lambda: ids_no_longer_present(some_files, SOME_DIRECTORY, held)
        ) \
        .then(_exactly_these_ids([]))


@pytest.mark.unit
def test_the_bounds_a_pass_is_given_are_what_the_fallback_cuts_by() -> None:
    # The configured pair arriving where it is used. Nothing else here would
    # notice if it did not: a pass that quietly cut by some default of its own
    # would index the repository perfectly well, and `CODE_INDEX_MAX_LINES`
    # would be a line in `.env` that changes nothing.
    #
    # A file with no structure this understands, because that is the only case
    # the bounds govern - Python is cut at its own definitions and ignores them.
    # Twelve lines: one passage at any ordinary width, four at this one.
    Scenario() \
        .given(
            some_files := {SOME_TEXT_PATH: SOME_PROSE_OF_TWELVE_LINES},
            a_narrow_window := 4,
            an_overlap_of := 1
        ) \
        .when(
            lambda: candidates_for(
                some_files, SOME_DIRECTORY, a_narrow_window, an_overlap_of
            )
        ) \
        .then(_exactly_this_many_candidates(4))


@pytest.mark.unit
def test_a_window_wide_enough_for_the_file_cuts_it_once() -> None:
    # The other half of the same claim. Four passages above could be four for
    # any number of reasons; the same file, the same call and a wider window
    # coming back as one is what says the number was read.
    Scenario() \
        .given(
            some_files := {SOME_TEXT_PATH: SOME_PROSE_OF_TWELVE_LINES},
            a_window_wider_than_the_file := 60,
            an_overlap_of := 10
        ) \
        .when(
            lambda: candidates_for(
                some_files,
                SOME_DIRECTORY,
                a_window_wider_than_the_file,
                an_overlap_of
            )
        ) \
        .then(_exactly_this_many_candidates(1))


def _exactly_this_many_candidates(expected: int) -> Assertion[list[Candidate]]:
    def exactly_this_many_candidates(candidates: list[Candidate]) -> bool:
        if len(candidates) != expected:
            raise AssertionError(
                f"Expected the file to be cut into [{expected}] passages, and "
                f"[{len(candidates)}] came back, spanning "
                f"{[(one.chunk.first_line, one.chunk.last_line) for one in candidates]}."
            )

        return True

    return exactly_this_many_candidates


def _the_ids_of(points: list[Point]) -> frozenset[str]:
    return frozenset(point.id for point in points)


def _no_point_carries_an_id_in(held: frozenset[str]) -> Assertion[list[Point]]:
    def no_point_carries_an_id_in(points: list[Point]) -> bool:
        already = [point.chunk.text for point in points if point.id in held]

        if already:
            raise AssertionError(
                f"Expected no point for a chunk the store already holds, "
                f"and {len(already)} came back: {already}."
            )

        return True

    return no_point_carries_an_id_in


def _an_embedder() -> Any:
    """A model that answers one vector per text, derived from the text itself.

    Derived rather than fixed, so a point wearing another chunk's vector is
    detectable: the vector says which text produced it. The batch's order is
    deliberately not part of it - a vector that encoded its position would agree
    with any pairing at all, including a wrong one.
    """
    embed = create_autospec(Embedder, instance=True)
    embed.side_effect = lambda texts: [_the_vector_for(text) for text in texts]

    return embed


def _the_vector_for(text: str) -> list[float]:
    return [float(len(text))]


def _exactly_this_many_points(expected: int) -> Assertion[list[Point]]:
    def exactly_this_many_points(points: list[Point]) -> bool:
        if len(points) != expected:
            raise AssertionError(
                f"Expected [{expected}] points, and [{len(points)}] came back, "
                f"naming {[point.chunk.path for point in points]}."
            )

        return True

    return exactly_this_many_points


def _every_point_names(path: str) -> Assertion[list[Point]]:
    def every_point_names(points: list[Point]) -> bool:
        wrong = [
            point.chunk.path for point in points if point.chunk.path != path
        ]

        if wrong:
            raise AssertionError(
                f"Expected every point to name [{path}], "
                f"and {len(wrong)} of them named {wrong}."
            )

        return True

    return every_point_names


def _no_point_names(path: str) -> Assertion[list[Point]]:
    def no_point_names(points: list[Point]) -> bool:
        if any(point.chunk.path == path for point in points):
            raise AssertionError(
                f"Expected no point to name [{path}], and one did - "
                f"a file outside the scope was indexed."
            )

        return True

    return no_point_names


def _every_point_embedded_its_own_text() -> Assertion[list[Point]]:
    def every_point_embedded_its_own_text(points: list[Point]) -> bool:
        mismatched = [
            point.chunk.path
            for point in points
            if point.vector != _the_vector_for(point.chunk.text)
        ]

        if mismatched:
            raise AssertionError(
                f"Expected every point to carry the vector its own text "
                f"embedded to, and {len(mismatched)} did not: {mismatched}."
            )

        return True

    return every_point_embedded_its_own_text


def _it_still_holds_the_ids_of(earlier: list[Point]) -> Assertion[list[Point]]:
    def it_still_holds_the_ids_of(points: list[Point]) -> bool:
        held = {point.id for point in points}
        lost = sorted(
            point.chunk.text for point in earlier if point.id not in held
        )

        if lost:
            raise AssertionError(
                f"Expected a chunk that only moved to keep its id, and "
                f"{len(lost)} were minted afresh: {lost}."
            )

        return True

    return it_still_holds_the_ids_of


def _every_id_is_distinct() -> Assertion[list[Point]]:
    def every_id_is_distinct(points: list[Point]) -> bool:
        ids = [point.id for point in points]

        if len(set(ids)) != len(ids):
            raise AssertionError(
                f"Expected every point to have an id of its own, "
                f"and these repeated: {ids}."
            )

        return True

    return every_id_is_distinct


def _the_embedder_was_called(embed: Any, times: int) -> Assertion[list[Point]]:
    def the_embedder_was_called(_: list[Point]) -> bool:
        if embed.call_count != times:
            raise AssertionError(
                f"Expected the embedder to be called [{times}] times, "
                f"and it was called [{embed.call_count}]."
            )

        return True

    return the_embedder_was_called


def _exactly_these_ids(expected: list[str]) -> Assertion[list[str]]:
    def exactly_these_ids(ids: list[str]) -> bool:
        if sorted(ids) != sorted(expected):
            raise AssertionError(
                f"Expected exactly {sorted(expected)}, and {sorted(ids)} "
                f"came back."
            )

        return True

    return exactly_these_ids
