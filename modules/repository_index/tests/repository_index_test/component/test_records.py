"""The marks saying which commit each build of the index describes.

Where the repository is, one row per repository, and which commit each recipe's
passages describe, one row per repository and recipe. The difference between
the two commits is the whole mechanism - the work list, the retry, and what a
reader is told when what it searched is not what is running.

Nothing here counts attempts or records that work is owed. A pass that failed
leaves the two commits differing, so the next pass finds the same work waiting
without anybody having written down that it does. That is why there is no
attempt column to assert on, and why these tests assert on the difference
instead.

Against a real database, because what is under test is a row: an upsert that
inserted twice, a null that came back as a string, a column that quietly
defaulted - none of those are things a fake would get wrong in the same way.
"""

from __future__ import annotations

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of
from repository_index.records import RepositoryIndex, get, record_indexed, record_pushed

SOME_REPOSITORY = "owner/some-service"
ANOTHER_REPOSITORY = "owner/another-service"

SOME_SHA = "9abaec7"
A_LATER_SHA = "cbe7bc3"

# Two recipes an index is built with, each a collection of its own - as
# `recipe.built_with` spells one, though what is spelled does not matter here.
SOME_RECIPE = "some-model lines=60 overlap=10 scope=src"
ANOTHER_RECIPE = "another-model lines=60 overlap=10 scope=src"


@pytest.mark.component
def test_a_repository_nothing_has_been_recorded_about_is_not_there(
    records: psycopg.Connection
) -> None:
    # Absent rather than an empty row. A repository the deployment has never
    # mentioned and one whose index has not been built yet are different
    # situations, and only the second is work.
    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(_nothing_was_recorded())


@pytest.mark.component
def test_a_pushed_commit_is_recorded_for_a_repository_never_seen_before(
    records: psycopg.Connection
) -> None:
    # The first push creates the row. Nothing registers a repository ahead of
    # time, so a write that required the row to exist would drop the first
    # notification about every repository there is.
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(
            all_of(
                _the_pending_commit_is(SOME_SHA),
                _the_indexed_commit_is(None)
            )
        )


@pytest.mark.component
def test_a_second_push_replaces_the_commit_the_first_reported(
    records: psycopg.Connection
) -> None:
    # Three pushes arriving before the index catches up must leave it aiming at
    # the third, not replaying the first two. Keeping only the latest is what
    # makes that true without a queue.
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_pushed(records, SOME_REPOSITORY, A_LATER_SHA)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(_the_pending_commit_is(A_LATER_SHA))


@pytest.mark.component
def test_a_finished_index_records_the_commit_it_described(
    records: psycopg.Connection
) -> None:
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_indexed(records, SOME_REPOSITORY, SOME_SHA, SOME_RECIPE)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(
            all_of(
                _the_indexed_commit_is(SOME_SHA),
                _it_says_when_it_was_indexed()
            )
        )


@pytest.mark.component
def test_a_finished_index_does_not_disturb_what_the_last_push_reported(
    records: psycopg.Connection
) -> None:
    # A push landing while an index is running is the case this protects. The
    # pass finishes and records the commit *it* built from; the newer commit
    # must still be sitting there afterwards, or the push is lost and the index
    # is quietly behind with nothing saying so.
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)
    record_pushed(records, SOME_REPOSITORY, A_LATER_SHA)

    Scenario() \
        .when(
            lambda: _recorded_then_read(records, SOME_REPOSITORY, SOME_SHA)
        ) \
        .then(
            all_of(
                _the_indexed_commit_is(SOME_SHA),
                _the_pending_commit_is(A_LATER_SHA)
            )
        )


@pytest.mark.component
def test_a_push_does_not_disturb_what_an_index_described(
    records: psycopg.Connection
) -> None:
    # The other order. A push says where the repository is, not what anybody
    # built - the mark has to stay where the pass left it, or the difference
    # that is the work list disappears with the push that made it.
    record_indexed(records, SOME_REPOSITORY, SOME_SHA, SOME_RECIPE)
    record_pushed(records, SOME_REPOSITORY, A_LATER_SHA)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(
            all_of(
                _the_indexed_commit_is(SOME_SHA),
                _the_pending_commit_is(A_LATER_SHA)
            )
        )


@pytest.mark.component
def test_an_index_that_finished_on_a_repository_never_pushed_is_recorded_too(
    records: psycopg.Connection
) -> None:
    # A first index that ran before any push arrived - the cold start, where
    # the catch-up pass asked the provider for the branch head itself rather than
    # waiting to be told.
    record_indexed(records, SOME_REPOSITORY, SOME_SHA, SOME_RECIPE)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(_the_indexed_commit_is(SOME_SHA))


@pytest.mark.component
def test_an_index_another_recipe_built_is_not_one_this_recipe_built(
    records: psycopg.Connection
) -> None:
    # Each recipe is a collection of its own. A mark another recipe left read
    # as this one's would call a collection current that nothing has built -
    # and a search of it would answer empty with nothing to say why.
    record_indexed(records, SOME_REPOSITORY, SOME_SHA, ANOTHER_RECIPE)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(_the_indexed_commit_is(None))


@pytest.mark.component
def test_each_recipe_keeps_the_commit_its_own_index_described(
    records: psycopg.Connection
) -> None:
    # Going back to a recipe built before resumes from that collection's own
    # commit. A mark shared between two would make it a whole pass over what
    # is there now, leaving every file deleted since in that collection.
    record_indexed(records, SOME_REPOSITORY, SOME_SHA, SOME_RECIPE)
    record_indexed(records, SOME_REPOSITORY, A_LATER_SHA, ANOTHER_RECIPE)

    Scenario() \
        .when(lambda: get(records, SOME_REPOSITORY, SOME_RECIPE)) \
        .then(_the_indexed_commit_is(SOME_SHA))


@pytest.mark.component
def test_one_repositorys_mark_is_not_anothers(
    records: psycopg.Connection
) -> None:
    # One row per repository, keyed by the name the API addresses it with. Two
    # services sharing a mark would have a push to one reindex the other.
    record_pushed(records, ANOTHER_REPOSITORY, A_LATER_SHA)
    record_pushed(records, ANOTHER_REPOSITORY, A_LATER_SHA)
    record_pushed(records, SOME_REPOSITORY, SOME_SHA)

    Scenario() \
        .when(lambda: get(records, ANOTHER_REPOSITORY, SOME_RECIPE)) \
        .then(_the_pending_commit_is(A_LATER_SHA))


def _recorded_then_read(conn: psycopg.Connection,
                        repository: str,
                        sha: str) -> RepositoryIndex | None:
    """Finishes an index, then reads the row back as one subject to assert on."""
    record_indexed(conn, repository, sha, SOME_RECIPE)

    return get(conn, repository, SOME_RECIPE)


def _nothing_was_recorded() -> Assertion[RepositoryIndex | None]:
    def nothing_was_recorded(found: RepositoryIndex | None) -> bool:
        if found is not None:
            raise AssertionError(
                f"Expected no row for a repository nothing was recorded about, "
                f"and [{found}] came back."
            )

        return True

    return nothing_was_recorded


def _the_pending_commit_is(expected: str | None) -> Assertion[RepositoryIndex | None]:
    def the_pending_commit_is(found: RepositoryIndex | None) -> bool:
        if found is None:
            raise AssertionError(
                f"Expected the pending commit to be [{expected}], "
                f"and there was no row at all."
            )

        if found.pending_sha != expected:
            raise AssertionError(
                f"Expected the pending commit to be [{expected}], "
                f"and it was [{found.pending_sha}]."
            )

        return True

    return the_pending_commit_is


def _the_indexed_commit_is(expected: str | None) -> Assertion[RepositoryIndex | None]:
    def the_indexed_commit_is(found: RepositoryIndex | None) -> bool:
        if found is None:
            raise AssertionError(
                f"Expected the indexed commit to be [{expected}], "
                f"and there was no row at all."
            )

        if found.indexed_sha != expected:
            raise AssertionError(
                f"Expected the indexed commit to be [{expected}], "
                f"and it was [{found.indexed_sha}]."
            )

        return True

    return the_indexed_commit_is


def _it_says_when_it_was_indexed() -> Assertion[RepositoryIndex | None]:
    """That a finished index left a time behind.

    Asked because "when did this last succeed" is the question somebody puts to
    an index that looks stale, and it cannot be answered from the commits alone.
    """
    def it_says_when_it_was_indexed(found: RepositoryIndex | None) -> bool:
        if found is None or found.indexed_at is None:
            raise AssertionError(
                f"Expected a finished index to record when it finished, "
                f"and [{found}] came back."
            )

        return True

    return it_says_when_it_was_indexed
