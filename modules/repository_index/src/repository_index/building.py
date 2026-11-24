"""Building the index for a repository at a commit.

Where the pieces meet. Read the source at the commit, ask the store what it
already holds, embed only what it does not, put those in, forget what the file
no longer has, and record which commit the passages now describe.

Backfill and incremental are the same call, which is the point. Nothing branches
on "is this the first time": an empty store holds nothing, so everything is
missing and everything is embedded. `paths` narrows which files are considered -
what a push hands you - and without it every file in the repository is.

The commit is recorded last and only on success. A pass that failed must leave
the difference between the two commits exactly where it was, because that
difference is the retry: nothing here counts attempts, and nothing else
remembers the work is owed.
"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from code_host import CodeHostReads
from core import SettingsSlice
from core.embedding import collection_for
from core.vector_store import VectorIndex

from repository_index.indexing import Candidate, Embedder, candidates_for, points_of
from repository_index.recipe import built_with
from repository_index.records import record_indexed
from repository_index.store import forget, ids_held_for, store_points


class IndexSettings(SettingsSlice):
    """What a pass is aimed at.

    Which directories of the repository are the service, which branch is
    deployed, where the passages are kept and what they are embedded by. Where
    the repository is and the credential that reads it are the code host's
    adapter's - a read credential alone, since building an index changes a
    repository in no way.
    """

    service_source_paths: str
    # The branch that is actually deployed, and so the one the index is meant
    # to describe. A pass aimed at anything else builds an index of code
    # nobody is running, which every later search answers from without ever
    # saying so.
    deployed_branch: str
    # The corpus the passages are kept as. The collection itself is named for
    # it and for the recipe, so each recipe is kept apart.
    repository_index_collection: str
    repository_index_embedding_model: str
    # How a file this cannot parse is cut into passages. Here rather than left
    # to the chunker's own defaults because a pass has to cut the way every
    # other pass over the same collection cut - which the recipe holds it to,
    # since the bounds are part of what a collection is named for.
    repository_index_max_lines: int
    repository_index_chunk_overlap: int

    @property
    def recipe(self) -> str:
        """What a pass builds with (`recipe.built_with`)."""
        return built_with(
            embedding_model=self.repository_index_embedding_model,
            service_source_paths=self.service_source_paths,
            max_lines=self.repository_index_max_lines,
            overlap=self.repository_index_chunk_overlap
        )

    @property
    def collection(self) -> str:
        """The collection this recipe's passages are kept in."""
        return collection_for(self.repository_index_collection, self.recipe)


def index_repository(sha: str,
                     *,
                     settings: IndexSettings,
                     conn: psycopg.Connection,
                     store: VectorIndex,
                     embed: Embedder,
                     code: CodeHostReads,
                     paths: list[str] | None = None) -> None:
    """Brings the index up to `sha`, for the whole repository or named paths,
    and records it under the repository the code host reads and the recipe
    `settings` build with. `store` is that recipe's collection.

    Raises whatever the code host raised. A repository that could not be
    fetched leaves the mark where it was, so the next pass finds the same work
    waiting - where swallowing it would record an index as current over
    passages nobody updated.
    """
    source = code.source_at(sha)

    for path in paths if paths is not None else list(source):
        _bring_one_file_up_to_date(path, source, settings, store, embed)

    record_indexed(conn, code.repository, sha, settings.recipe)


def _bring_one_file_up_to_date(path: str,
                               source: Mapping[str, str],
                               settings: IndexSettings,
                               store: VectorIndex,
                               embed: Embedder) -> None:
    """One file, brought to what it now says - including saying nothing.

    A path the pass was told about and the source does not have is a deletion,
    and it reaches here as a file that yields no passages. Nothing else would
    ever forget it: the file is gone, so no later pass considers it.
    """
    held = ids_held_for(store, path)
    wanted = _the_passages_of(path, source, settings)

    _put_in_what_is_missing(wanted, held, settings, store, embed)
    forget(store, [one for one in held if one not in {candidate.id for candidate in wanted}])


def _the_passages_of(path: str,
                     source: Mapping[str, str],
                     settings: IndexSettings) -> list[Candidate]:
    """What this file cuts into now, named and not yet embedded.

    Empty where the file is gone, and empty where it is not the service's own -
    which are different reasons for the same right answer, since neither leaves
    anything that ought to be retrievable.
    """
    said = source.get(path)

    if said is None:
        return []

    return candidates_for(
        {path: said},
        settings.service_source_paths,
        max_lines=settings.repository_index_max_lines,
        overlap=settings.repository_index_chunk_overlap
    )


def _put_in_what_is_missing(wanted: list[Candidate],
                            held: set[str],
                            settings: IndexSettings,
                            store: VectorIndex,
                            embed: Embedder) -> None:
    """Embeds and stores the passages the store does not already hold.

    The vector's width is read off the vectors rather than configured. It is a
    fact about the model, and a configured copy of it is a second statement of
    the same thing - wrong exactly when somebody swaps the model and forgets.
    """
    points = points_of(wanted, embed, held_ids=frozenset(held))

    if not points:
        return

    store_points(store, points, width=len(points[0].vector))
