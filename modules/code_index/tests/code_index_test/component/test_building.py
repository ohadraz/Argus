"""Building the index for a repository at a commit.

Where the pieces meet: read the source at the commit, ask the store what it
already holds, embed only what it does not, put those in, forget what the file
no longer has, and record which commit the passages now describe.

Backfill and incremental are the same call. Nothing branches on "is this the
first time" - an empty store simply holds nothing, so everything is missing and
everything is embedded. `paths` narrows which files are considered, which is
what a push gives you; without it every file in the repository is.

Against both real things. The store holds the passages and the database holds
the mark, and a test that faked either would be asserting that two things it
wrote agree with each other. The embedder is the one collaborator that stays a
double: it is the only one that would otherwise load a model.

The commit is recorded last and only on success. A pass that failed must leave
the difference between the two commits exactly where it was, because that
difference is the retry - there is nothing else that remembers the work is owed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from code_index.building import IndexSettings, SourceReader, index_repository
from code_index.indexing import Embedder
from code_index.records import get
from code_index.store import chunks_held_for, ids_held_for
from qdrant_client import QdrantClient
from repository_source import RepositoryUnreadable

# What a file this cannot parse is cut by. The fixtures here are Python and are
# cut at their own definitions, so these govern nothing in this suite - they are
# a pair `Settings` would accept, said out loud rather than defaulted.
SOME_MAX_LINES = 60
SOME_OVERLAP = 10

SOME_COLLECTION = "code_index_building_test"
SOME_REPOSITORY = "owner/some-service"
SOME_DIRECTORY = "src/shop"

SOME_PATH = f"{SOME_DIRECTORY}/summary.py"
ANOTHER_PATH = f"{SOME_DIRECTORY}/accounts.py"
SOME_PATH_OUT_OF_SCOPE = "harness/scenarios.py"

SOME_SHA = "9abaec7"
A_LATER_SHA = "cbe7bc3"
DONT_CARE_BRANCH = "main"

SOME_SOURCE = "def summary() -> None:\n    return None\n"
ANOTHER_SOURCE = "def accounts() -> None:\n    return None\n"
SOME_EDITED_SOURCE = "def summary() -> int:\n    return 1\n"


@pytest.mark.component
def test_every_file_in_the_repository_ends_up_in_the_store(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    Scenario() \
        .when(
            lambda: _indexed(
                store, records, {SOME_PATH: SOME_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE}
            )
        ) \
        .then(
            all_of(
                _the_store_holds_something_for(store, SOME_PATH),
                _the_store_holds_something_for(store, ANOTHER_PATH)
            )
        )


@pytest.mark.component
def test_a_finished_index_records_the_commit_it_was_built_from(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # Without this the index is current and cannot say so, and the catch-up pass
    # rebuilds it on every pass forever.
    Scenario() \
        .when(lambda: _indexed(store, records, {SOME_PATH: SOME_SOURCE})) \
        .then(_the_recorded_commit_is(records, SOME_SHA))


@pytest.mark.component
def test_a_file_outside_the_scope_never_reaches_the_store(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # The harness that stages incidents. An agent retrieving it is retrieving
    # how its own incidents are made.
    Scenario() \
        .when(
            lambda: _indexed(
                store,
                records,
                {SOME_PATH: SOME_SOURCE, SOME_PATH_OUT_OF_SCOPE: ANOTHER_SOURCE}
            )
        ) \
        .then(_the_store_holds_nothing_for(store, SOME_PATH_OUT_OF_SCOPE))


@pytest.mark.component
def test_a_second_pass_over_unchanged_source_embeds_nothing(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # The common case on every push: one file changed and the rest did not. The
    # rest must cost nothing, which is what the content-derived id is for.
    some_files = {SOME_PATH: SOME_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE}
    _indexed(store, records, some_files)
    embed = _an_embedder()

    Scenario() \
        .when(lambda: _indexed(store, records, some_files, embed=embed)) \
        .then(_the_embedder_was_never_called(embed))


@pytest.mark.component
def test_reindexing_a_changed_file_removes_the_old_version(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # The delete side. Without it the store answers with the passage as it was
    # as well as the passage as it is, and a reader cannot tell which is which.
    _indexed(store, records, {SOME_PATH: SOME_SOURCE})

    Scenario() \
        .when(
            lambda: _indexed_then_read(
                store, records, {SOME_PATH: SOME_EDITED_SOURCE}, SOME_PATH
            )
        ) \
        .then(
            all_of(
                _a_passage_reads("def summary() -> int:\n    return 1"),
                _no_passage_reads("def summary() -> None:\n    return None")
            )
        )


@pytest.mark.component
def test_naming_the_paths_that_changed_leaves_the_others_alone(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # What a push gives you. A pass told which files moved must not re-examine
    # the rest - and must not drop them either, which is the failure mode worth
    # pinning: a narrowed pass that forgot everything it did not look at.
    _indexed(store, records, {SOME_PATH: SOME_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE})

    Scenario() \
        .when(
            lambda: _indexed(
                store,
                records,
                {SOME_PATH: SOME_EDITED_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE},
                paths=[SOME_PATH]
            )
        ) \
        .then(_the_store_holds_something_for(store, ANOTHER_PATH))


@pytest.mark.component
def test_a_file_a_push_removed_is_forgotten(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # A path named by the push and absent from the source is a deletion. Nothing
    # else would ever forget it: the file is gone, so no later pass considers it.
    _indexed(store, records, {SOME_PATH: SOME_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE})

    Scenario() \
        .when(
            lambda: _indexed(
                store, records, {ANOTHER_PATH: ANOTHER_SOURCE}, paths=[SOME_PATH]
            )
        ) \
        .then(_the_store_holds_nothing_for(store, SOME_PATH))


@pytest.mark.component
def test_a_repository_that_could_not_be_read_does_not_move_the_mark(
    store: QdrantClient, records: psycopg.Connection
) -> None:
    # The level-triggered guarantee. Nothing counts attempts, so a pass that
    # failed must leave the difference between the two commits exactly where it
    # was - that difference is the only thing that remembers the work is owed.
    _indexed(store, records, {SOME_PATH: SOME_SOURCE})

    Scenario() \
        .when(
            attempting(
                lambda: _indexed(
                    store, records, {}, sha=A_LATER_SHA, unreadable=True
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable),
                _the_recorded_commit_is(records, SOME_SHA)
            )
        )


def _indexed(store: QdrantClient,
             records: psycopg.Connection,
             files: dict[str, str],
             sha: str = SOME_SHA,
             paths: list[str] | None = None,
             embed: Any = None,
             unreadable: bool = False) -> None:
    """One pass, with the source handed over rather than fetched.

    The reader is the seam: fetching an archive belongs to `repository_source`
    and is tested there, and a pass that had to build a tarball to be exercised
    would be testing somebody else's unpacking to reach its own subject.
    """
    index_repository(
        SOME_REPOSITORY,
        sha,
        settings=_some_settings(),
        conn=records,
        store=store,
        embed=embed or _an_embedder(),
        read_source=_a_source_reader(files, unreadable),
        paths=paths
    )


def _indexed_then_read(store: QdrantClient,
                       records: psycopg.Connection,
                       files: dict[str, str],
                       path: str) -> list[str]:
    """A pass, then what the store says about one file - one subject to assert."""
    _indexed(store, records, files)

    return [chunk.text for chunk in chunks_held_for(store, SOME_COLLECTION, path)]


def _some_settings() -> IndexSettings:
    return IndexSettings(
        github_api_url="https://api.github.invalid",
        github_repository=SOME_REPOSITORY,
        github_read_token="ghp_dont-care-read-token",
        github_source_paths=SOME_DIRECTORY,
        github_base_branch=DONT_CARE_BRANCH,
        code_index_collection=SOME_COLLECTION,
        code_index_max_lines=SOME_MAX_LINES,
        code_index_chunk_overlap=SOME_OVERLAP
    )


def _a_source_reader(files: dict[str, str], unreadable: bool) -> Any:
    """A stand-in for `repository_source.the_source_at`.

    Spec'd against the `Protocol` the pass asks by rather than against the real
    function, for the reason the fix loop's ports are: the pass is asked about a
    repository, where the function takes the settings to reach one with.
    """
    reader = create_autospec(SourceReader, instance=True)

    if unreadable:
        reader.side_effect = RepositoryUnreadable("no route to host")
    else:
        reader.return_value = files

    return reader


def _an_embedder() -> Any:
    """A model answering one vector per text, derived from the text itself."""
    embed = create_autospec(Embedder, instance=True)
    embed.side_effect = lambda texts: [[float(len(text))] for text in texts]

    return embed


def _the_store_holds_something_for(store: QdrantClient,
                                   path: str) -> Assertion[object]:
    def the_store_holds_something_for(_: object) -> bool:
        if not ids_held_for(store, SOME_COLLECTION, path):
            raise AssertionError(
                f"Expected the store to hold passages for [{path}], "
                f"and it held none."
            )

        return True

    return the_store_holds_something_for


def _the_store_holds_nothing_for(store: QdrantClient,
                                 path: str) -> Assertion[object]:
    def the_store_holds_nothing_for(_: object) -> bool:
        held = ids_held_for(store, SOME_COLLECTION, path)

        if held:
            raise AssertionError(
                f"Expected the store to hold nothing for [{path}], "
                f"and it held [{len(held)}] passages."
            )

        return True

    return the_store_holds_nothing_for


def _the_recorded_commit_is(records: psycopg.Connection,
                            expected: str) -> Assertion[object]:
    def the_recorded_commit_is(_: object) -> bool:
        found = get(records, SOME_REPOSITORY)
        indexed = found.indexed_sha if found else None

        if indexed != expected:
            raise AssertionError(
                f"Expected the passages to be recorded as describing "
                f"[{expected}], and the mark reads [{indexed}]."
            )

        return True

    return the_recorded_commit_is


def _the_embedder_was_never_called(embed: Any) -> Assertion[object]:
    def the_embedder_was_never_called(_: object) -> bool:
        if embed.call_count:
            raise AssertionError(
                f"Expected nothing to be embedded for source that had not "
                f"changed, and the embedder was called "
                f"[{embed.call_count}] times."
            )

        return True

    return the_embedder_was_never_called


def _a_passage_reads(text: str) -> Assertion[list[str]]:
    def a_passage_reads(held: list[str]) -> bool:
        if not any(passage.strip() == text.strip() for passage in held):
            raise AssertionError(
                f"Expected a passage reading [{text!r}], and what is held is "
                f"{[passage.strip() for passage in held]}."
            )

        return True

    return a_passage_reads


def _no_passage_reads(text: str) -> Assertion[list[str]]:
    def no_passage_reads(held: list[str]) -> bool:
        if any(passage.strip() == text.strip() for passage in held):
            raise AssertionError(
                f"Expected no passage reading [{text!r}] - it was edited away - "
                f"and it is still held."
            )

        return True

    return no_passage_reads
