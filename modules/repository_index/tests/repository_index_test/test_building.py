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
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting, calling
from code_host import CodeHostReads, RepositoryUnreadable
from repository_index.building import IndexSettings, index_repository
from repository_index.indexing import Embedder
from repository_index.records import get
from repository_index.store import chunks_held_for, ids_held_for
from vector_store_qdrant.indexing import QdrantIndex

# What a file this cannot parse is cut by. The fixtures here are Python and are
# cut at their own definitions, so these govern nothing in this suite - they are
# a pair `Settings` would accept, said out loud rather than defaulted.
SOME_MAX_LINES = 60
SOME_OVERLAP = 10
# Required by the settings and read by nothing here: the store a pass is handed
# is bound to its collection where it is built.
DONT_CARE_COLLECTION = "repository_index_building_test"
# The model the settings name. Nothing here loads it - the embedder is a double
# - but it is part of the recipe the mark is filed under.
SOME_EMBEDDING_MODEL = "some-embedding-model"
ANOTHER_EMBEDDING_MODEL = "another-embedding-model"
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


@pytest.mark.integration
def test_every_file_in_the_repository_ends_up_in_the_store(
    store: QdrantIndex, records: psycopg.Connection
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


@pytest.mark.integration
def test_a_finished_index_records_the_commit_it_was_built_from(
    store: QdrantIndex, records: psycopg.Connection
) -> None:
    # Without this the index is current and cannot say so, and the catch-up pass
    # rebuilds it on every pass forever.
    Scenario() \
        .when(lambda: _indexed(store, records, {SOME_PATH: SOME_SOURCE})) \
        .then(_the_recorded_commit_is(records, SOME_SHA))


@pytest.mark.unit
def test_another_embedding_model_keeps_its_passages_in_another_collection() -> None:
    # A vector means something only beside vectors the same model made, so a
    # pass built by another model never writes into this one's collection.
    Scenario() \
        .when(lambda: _some_settings(embedding_model=ANOTHER_EMBEDDING_MODEL).collection) \
        .then(_not(_some_settings().collection))


@pytest.mark.integration
def test_a_file_outside_the_scope_never_reaches_the_store(
    store: QdrantIndex, records: psycopg.Connection
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


@pytest.mark.integration
def test_a_second_pass_over_unchanged_source_embeds_nothing(
    store: QdrantIndex, records: psycopg.Connection
) -> None:
    # The common case on every push: one file changed and the rest did not. The
    # rest must cost nothing, which is what the content-derived id is for.
    some_files = {SOME_PATH: SOME_SOURCE, ANOTHER_PATH: ANOTHER_SOURCE}

    Scenario() \
        .given(
            calling(lambda: _indexed(store, records, some_files)),
            embed := _an_embedder()
        ) \
        .when(lambda: _indexed(store, records, some_files, embed=embed)) \
        .then(_the_embedder_was_never_called(embed))


@pytest.mark.integration
def test_reindexing_a_changed_file_removes_the_old_version(
    store: QdrantIndex, records: psycopg.Connection
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


@pytest.mark.integration
def test_naming_the_paths_that_changed_leaves_the_others_alone(
    store: QdrantIndex, records: psycopg.Connection
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


@pytest.mark.integration
def test_a_file_a_push_removed_is_forgotten(
    store: QdrantIndex, records: psycopg.Connection
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


@pytest.mark.integration
def test_a_repository_that_could_not_be_read_does_not_move_the_mark(
    store: QdrantIndex, records: psycopg.Connection
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


def _indexed(store: QdrantIndex,
             records: psycopg.Connection,
             files: dict[str, str],
             sha: str = SOME_SHA,
             paths: list[str] | None = None,
             embed: Any = None,
             unreadable: bool = False) -> None:
    """One pass, with the source handed over rather than fetched.

    The code host is the seam: fetching an archive belongs to its adapter and is
    tested there, and a pass that had to build a tarball to be exercised would
    be testing somebody else's unpacking to reach its own subject.
    """
    index_repository(
        sha,
        settings=_some_settings(),
        conn=records,
        store=store,
        embed=embed or _an_embedder(),
        code=_a_code_host_whose_source_is(files, unreadable),
        paths=paths
    )


def _indexed_then_read(store: QdrantIndex,
                       records: psycopg.Connection,
                       files: dict[str, str],
                       path: str) -> list[str]:
    """A pass, then what the store says about one file - one subject to assert."""
    _indexed(store, records, files)

    return [chunk.text for chunk in chunks_held_for(store, path)]


def _some_settings(embedding_model: str = SOME_EMBEDDING_MODEL) -> IndexSettings:
    return IndexSettings(
        service_source_paths=SOME_DIRECTORY,
        deployed_branch=DONT_CARE_BRANCH,
        repository_index_collection=DONT_CARE_COLLECTION,
        repository_index_embedding_model=embedding_model,
        repository_index_max_lines=SOME_MAX_LINES,
        repository_index_chunk_overlap=SOME_OVERLAP
    )


def _a_code_host_whose_source_is(files: dict[str, str], unreadable: bool) -> Any:
    """The code host's reads port, for `SOME_REPOSITORY`, answering the whole
    source with `files` - or refusing to."""
    code = create_autospec(CodeHostReads, instance=True)
    code.repository = SOME_REPOSITORY

    if unreadable:
        code.source_at.side_effect = RepositoryUnreadable("no route to host")
    else:
        code.source_at.return_value = files

    return code


def _an_embedder() -> Any:
    """A model answering one vector per text, derived from the text itself."""
    embed = create_autospec(Embedder, instance=True)
    embed.side_effect = lambda texts: [[float(len(text))] for text in texts]

    return embed


def _the_store_holds_something_for(store: QdrantIndex,
                                   path: str) -> Assertion[object]:
    def the_store_holds_something_for(_: object) -> bool:
        if not ids_held_for(store, path):
            raise AssertionError(
                f"Expected the store to hold passages for [{path}], "
                f"and it held none."
            )

        return True

    return the_store_holds_something_for


def _the_store_holds_nothing_for(store: QdrantIndex,
                                 path: str) -> Assertion[object]:
    def the_store_holds_nothing_for(_: object) -> bool:
        held = ids_held_for(store, path)

        if held:
            raise AssertionError(
                f"Expected the store to hold nothing for [{path}], "
                f"and it held [{len(held)}] passages."
            )

        return True

    return the_store_holds_nothing_for


def _the_recorded_commit_is(records: psycopg.Connection,
                            expected: str) -> Assertion[object]:
    """The commit on record for the recipe the pass was built with - the only
    mark a later pass with the same settings reads."""
    def the_recorded_commit_is(_: object) -> bool:
        found = get(records, SOME_REPOSITORY, _some_settings().recipe)
        indexed = found.indexed_sha if found else None

        if indexed != expected:
            raise AssertionError(
                f"Expected the passages to be recorded as describing "
                f"[{expected}], and the mark reads [{indexed}]."
            )

        return True

    return the_recorded_commit_is


def _not(other: str) -> Assertion[str]:
    def assertion(collection: str) -> bool:
        if collection == other:
            raise AssertionError(f"Expected a collection other than [{other}], got the same.")

        return True

    return assertion


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
