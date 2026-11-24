"""The marks saying which commit each build of the index describes.

Two tables. Where the repository is - the commit the last push reported - is
one row per repository, because it does not depend on how anybody indexes it.
Which commit the stored passages describe is one row per repository and recipe
(`built_with`), because each recipe is a collection of its own and a mark
shared between two would describe one of them wrongly. The difference between
the two commits is the work list, the retry, and what a reader is told when
what it searched is not what is running.

Nothing here counts attempts or records that work is owed. A pass that failed
leaves the two commits differing, so the next pass finds the same work waiting
without anybody having written down that it does - which is why there is no
attempt column, no backoff and no queue of unprocessed notifications. The state
is the goal, not the history of trying to reach it.

The vectors live in the store and the marks live here, and that split is
deliberate: a store answers "what passages are near this" well and "what commit
is this collection as of" not at all.
"""

from __future__ import annotations

from datetime import datetime

import psycopg
from pydantic import BaseModel


class RepositoryIndex(BaseModel):
    """What is on record about one repository's index, as one recipe built it.

    Both commits are optional and mean different absences. No `indexed_sha` is
    an index this recipe has never built - a backfill, into a collection of its
    own. No `pending_sha` is a repository nothing has reported a push for yet,
    which is the ordinary state of a first deployment and means the catch-up
    pass must ask the provider for the deployed branch's head rather than wait
    to be told.
    """

    repository: str
    indexed_sha: str | None = None
    pending_sha: str | None = None
    indexed_at: datetime | None = None


def get(conn: psycopg.Connection, repository: str, built_with: str) -> RepositoryIndex | None:
    """What is on record about `repository`, with what `built_with` built of
    it, or nothing.

    A bare `get`, which the naming rule allows because the arguments are the
    identity: a repository is addressed as `owner/name`, and a build of it by
    the recipe it was built with.

    `None` is a repository nothing has been recorded about at all, which is a
    different thing from one this recipe has not built - and only the second
    is work.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT index.repository, build.indexed_sha, index.pending_sha, build.indexed_at
            FROM repository_index AS index
            LEFT JOIN repository_index_build AS build
                ON build.repository = index.repository AND build.built_with = %s
            WHERE index.repository = %s
            """,
            (built_with, repository)
        )
        found = cursor.fetchone()

    if found is None:
        return None

    repository_name, indexed_sha, pending_sha, indexed_at = found

    return RepositoryIndex(
        repository=repository_name,
        indexed_sha=indexed_sha,
        pending_sha=pending_sha,
        indexed_at=indexed_at
    )


def record_pushed(conn: psycopg.Connection,
                  repository: str,
                  sha: str) -> None:
    """Records where the repository now is.

    Creates the row if there is none, because nothing registers a repository
    ahead of time and a write that required the row to exist would drop the
    first notification about every repository there is.

    Replaces rather than accumulates. Three pushes arriving before the index
    catches up must leave it aiming at the third, and keeping only the latest is
    what makes that true without a queue to drain. Every build's mark is left
    where it was: a push says where the repository is, not what anybody built.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO repository_index (repository, pending_sha)
            VALUES (%s, %s)
            ON CONFLICT (repository) DO UPDATE SET pending_sha = EXCLUDED.pending_sha
            """,
            (repository, sha)
        )

    conn.commit()


def record_indexed(conn: psycopg.Connection,
                   repository: str,
                   sha: str,
                   built_with: str) -> None:
    """Records that the passages `built_with` built now describe `sha`.

    Leaves `pending_sha` alone, which is the point. A push landing while an
    index is running would otherwise be overwritten by the pass that started
    before it: the index would record itself current while describing a commit
    that had already been superseded, and nothing would say so. Leaves every
    other recipe's mark alone as well, since each describes a collection of its
    own.

    Creates the repository's row where there is none, as `record_pushed` does:
    a first index finishes before any push has been reported.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO repository_index (repository) VALUES (%s) ON CONFLICT DO NOTHING",
            (repository,)
        )
        cursor.execute(
            """
            INSERT INTO repository_index_build (repository, built_with, indexed_sha, indexed_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (repository, built_with) DO UPDATE SET
                indexed_sha = EXCLUDED.indexed_sha,
                indexed_at = EXCLUDED.indexed_at
            """,
            (repository, built_with, sha)
        )

    conn.commit()
