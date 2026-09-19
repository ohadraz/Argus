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
from typing import Protocol

import psycopg
from argus_core import SettingsSlice
from qdrant_client import QdrantClient
from repository_source import RepositorySourceSettings, the_source_at

from code_index.indexing import Candidate, Embedder, candidates_for, points_of
from code_index.records import record_indexed
from code_index.store import forget, ids_held_for, store_points


class SourceReader(Protocol):
    """How a pass gets hold of the repository's source.

    A seam rather than the call itself, because a test of this module has no
    business building a tarball: fetching an archive and unwrapping it belongs
    to `repository_source` and is asserted there.
    """

    def __call__(self,
                 ref: str,
                 settings: RepositorySourceSettings,
                 /) -> dict[str, str]: ...


class IndexSettings(SettingsSlice):
    """What a pass is aimed at.

    The repository and the credential that reads it, which directories of it are
    the service, and where the passages are kept. No write credential: building
    an index changes a repository in no way, and a slice that named one would be
    handing this process a capability it has no use for.
    """

    github_api_url: str
    github_repository: str
    github_read_token: str
    github_source_paths: str
    # The branch that is actually deployed, and so the one the index is meant
    # to describe. A pass aimed at anything else builds an index of code
    # nobody is running, which every later search answers from without ever
    # saying so.
    github_base_branch: str
    code_index_collection: str
    # How a file this cannot parse is cut into passages. Here rather than left
    # to the chunker's own defaults because a pass has to cut the way every
    # other pass over the same store cut: an id is derived from what a passage
    # says, so the same file under different bounds is a second set of points
    # beside the first rather than a replacement for it.
    code_index_max_lines: int
    code_index_chunk_overlap: int


def index_repository(repository: str,
                     sha: str,
                     *,
                     settings: IndexSettings,
                     conn: psycopg.Connection,
                     store: QdrantClient,
                     embed: Embedder,
                     read_source: SourceReader = the_source_at,
                     paths: list[str] | None = None) -> None:
    """Brings the index up to `sha`, for the whole repository or named paths.

    Raises whatever the reader raised. A repository that could not be fetched
    leaves the mark where it was, so the next pass finds the same work waiting -
    where swallowing it would record an index as current over passages nobody
    updated.
    """
    source = read_source(sha, _the_source_settings(settings))

    for path in paths if paths is not None else list(source):
        _bring_one_file_up_to_date(path, source, settings, store, embed)

    record_indexed(conn, repository, sha)


def _bring_one_file_up_to_date(path: str,
                               source: Mapping[str, str],
                               settings: IndexSettings,
                               store: QdrantClient,
                               embed: Embedder) -> None:
    """One file, brought to what it now says - including saying nothing.

    A path the pass was told about and the source does not have is a deletion,
    and it reaches here as a file that yields no passages. Nothing else would
    ever forget it: the file is gone, so no later pass considers it.
    """
    held = ids_held_for(store, settings.code_index_collection, path)
    wanted = _the_passages_of(path, source, settings)

    _put_in_what_is_missing(wanted, held, settings, store, embed)
    forget(
        store,
        settings.code_index_collection,
        [one for one in held if one not in {candidate.id for candidate in wanted}]
    )


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
        settings.github_source_paths,
        max_lines=settings.code_index_max_lines,
        overlap=settings.code_index_chunk_overlap
    )


def _put_in_what_is_missing(wanted: list[Candidate],
                            held: set[str],
                            settings: IndexSettings,
                            store: QdrantClient,
                            embed: Embedder) -> None:
    """Embeds and stores the passages the store does not already hold.

    The vector's width is read off the vectors rather than configured. It is a
    fact about the model, and a configured copy of it is a second statement of
    the same thing - wrong exactly when somebody swaps the model and forgets.
    """
    points = points_of(wanted, embed, held_ids=frozenset(held))

    if not points:
        return

    store_points(
        store,
        settings.code_index_collection,
        points,
        width=len(points[0].vector)
    )


def _the_source_settings(settings: IndexSettings) -> RepositorySourceSettings:
    """The reader's view: a repository and a credential, and nothing else."""
    return RepositorySourceSettings(
        github_api_url=settings.github_api_url,
        github_repository=settings.github_repository,
        github_read_token=settings.github_read_token
    )
