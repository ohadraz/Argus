"""Whether the index describes the code that is deployed.

One comparison, and the whole of what the rest of the module hangs off. The
reconciler reads it to decide whether there is work; retrieval reads it to
decide whether an answer needs a warning on it; Code-Fix reads it to decide
what to tell the model before it starts reading passages.

Three states, not two. An index that has never been built and one that has
fallen behind are both "not current" and are not the same thing: the first is a
backfill and the second is a handful of changed paths, and a reconciler that
could not tell them apart would re-index a whole repository to catch up on one
file. `indexed_sha is None` is what says nothing has been indexed - the absence
of a mark rather than a mark that happens to differ.

The stored mark is what `design.md` calls the watermark. This is the question
asked of it, which is why the type is named for the comparison and not for the
mark.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of
from code_index.freshness import Freshness

# Real shas, because a sha that reads as a word invites a reader to think the
# comparison knows something about its contents. It knows only whether two
# strings are the same one.
SOME_INDEXED_SHA = "9abaec7"
SOME_LATER_SHA = "cbe7bc3"


@pytest.mark.unit
def test_an_index_describing_the_deployed_commit_is_current() -> None:
    Scenario() \
        .given(some_sha := SOME_INDEXED_SHA) \
        .when(lambda: Freshness(indexed_sha=some_sha, deployed_sha=some_sha)) \
        .then(
            all_of(
                _it_reads_as_current(True),
                _it_reads_as_never_indexed(False)
            )
        )


@pytest.mark.unit
def test_an_index_describing_an_earlier_commit_is_behind() -> None:
    Scenario() \
        .given(the_indexed_sha := SOME_INDEXED_SHA, the_deployed_sha := SOME_LATER_SHA) \
        .when(
            lambda: Freshness(
                indexed_sha=the_indexed_sha, deployed_sha=the_deployed_sha
            )
        ) \
        .then(
            all_of(
                _it_reads_as_current(False),
                _it_reads_as_never_indexed(False)
            )
        )


@pytest.mark.unit
def test_an_index_that_was_never_built_is_not_current() -> None:
    # The cold start. Not a special case anywhere else in the module - a
    # backfill is reconciliation from an empty actual state - but it has to be
    # distinguishable here, because it is the one case with no paths to narrow
    # the work to.
    Scenario() \
        .given(nothing_indexed := None, the_deployed_sha := SOME_LATER_SHA) \
        .when(
            lambda: Freshness(
                indexed_sha=nothing_indexed, deployed_sha=the_deployed_sha
            )
        ) \
        .then(
            all_of(
                _it_reads_as_current(False),
                _it_reads_as_never_indexed(True)
            )
        )


@pytest.mark.unit
def test_a_behind_index_carries_both_commits() -> None:
    # What retrieval prefixes onto its answer and what Code-Fix is opened with.
    # Asserted because "it is behind" alone sends somebody to compare two
    # things they were not told the names of.
    Scenario() \
        .given(the_indexed_sha := SOME_INDEXED_SHA, the_deployed_sha := SOME_LATER_SHA) \
        .when(
            lambda: Freshness(
                indexed_sha=the_indexed_sha, deployed_sha=the_deployed_sha
            )
        ) \
        .then(
            all_of(
                _it_says_it_indexed(SOME_INDEXED_SHA),
                _it_says_the_deployed_commit_is(SOME_LATER_SHA)
            )
        )


@pytest.mark.unit
def test_a_behind_index_tells_a_reader_both_commits() -> None:
    Scenario() \
        .given(
            the_indexed_sha := SOME_INDEXED_SHA,
            the_deployed_sha := SOME_LATER_SHA
        ) \
        .when(
            lambda: Freshness(
                indexed_sha=the_indexed_sha, deployed_sha=the_deployed_sha
            ).notice
        ) \
        .then(
            all_of(
                _it_mentions(SOME_INDEXED_SHA),
                _it_mentions(SOME_LATER_SHA)
            )
        )


@pytest.mark.unit
def test_a_current_index_tells_a_reader_nothing() -> None:
    # The rule lives here rather than in each caller. Retrieval prefixes this
    # onto its answer and Code-Fix opens with it, and two callers each deciding
    # when to stay quiet is two places for a stale warning to survive.
    Scenario() \
        .given(some_sha := SOME_INDEXED_SHA) \
        .when(
            lambda: Freshness(indexed_sha=some_sha, deployed_sha=some_sha).notice
        ) \
        .then(_it_said_nothing())


@pytest.mark.unit
def test_an_index_that_was_never_built_says_so_rather_than_naming_a_commit() -> None:
    # An empty index and a behind one both warrant a notice, and not the same
    # one: "what you retrieve may be out of date" is the wrong thing to say
    # when the answer to every query is going to be nothing at all.
    Scenario() \
        .given(nothing_indexed := None, the_deployed_sha := SOME_LATER_SHA) \
        .when(
            lambda: Freshness(
                indexed_sha=nothing_indexed, deployed_sha=the_deployed_sha
            ).notice
        ) \
        .then(_it_mentions("nothing has been indexed"))


def _it_reads_as_current(expected: bool) -> Assertion[Freshness]:
    def reads_as_current(freshness: Freshness) -> bool:
        if freshness.is_current != expected:
            raise AssertionError(
                f"Expected is_current to be [{expected}] for an index at "
                f"[{freshness.indexed_sha}] against a repository at "
                f"[{freshness.deployed_sha}], and it was "
                f"[{freshness.is_current}]."
            )

        return True

    return reads_as_current


def _it_reads_as_never_indexed(expected: bool) -> Assertion[Freshness]:
    def reads_as_never_indexed(freshness: Freshness) -> bool:
        if freshness.has_never_been_indexed != expected:
            raise AssertionError(
                f"Expected has_never_been_indexed to be [{expected}] for an "
                f"index at [{freshness.indexed_sha}], and it was "
                f"[{freshness.has_never_been_indexed}]."
            )

        return True

    return reads_as_never_indexed


def _it_says_it_indexed(expected: str) -> Assertion[Freshness]:
    def says_it_indexed(freshness: Freshness) -> bool:
        if freshness.indexed_sha != expected:
            raise AssertionError(
                f"Expected the indexed commit to read [{expected}], "
                f"and it read [{freshness.indexed_sha}]."
            )

        return True

    return says_it_indexed


def _it_says_the_deployed_commit_is(expected: str) -> Assertion[Freshness]:
    def says_the_deployed_commit_is(freshness: Freshness) -> bool:
        if freshness.deployed_sha != expected:
            raise AssertionError(
                f"Expected the deployed commit to read [{expected}], "
                f"and it read [{freshness.deployed_sha}]."
            )

        return True

    return says_the_deployed_commit_is


def _it_mentions(expected: str) -> Assertion[str | None]:
    """That the notice said a thing the reader needs in order to act.

    A substring rather than the whole sentence. What matters is that the reader
    is handed the commits; the prose around them is free to be reworded without
    a test failing for a reason that is not a behaviour change.
    """
    def mentions(notice: str | None) -> bool:
        if notice is None or expected not in notice:
            raise AssertionError(
                f"Expected the notice to mention [{expected}], "
                f"and it read [{notice}]."
            )

        return True

    return mentions


def _it_said_nothing() -> Assertion[str | None]:
    def said_nothing(notice: str | None) -> bool:
        if notice is not None:
            raise AssertionError(
                f"Expected a current index to say nothing, "
                f"and it said [{notice}]."
            )

        return True

    return said_nothing
