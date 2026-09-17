"""Bringing the index up to what is deployed (spec §11).

One pass, and one decision in it: what commit the passages describe, what
commit the repository is at, and the work between them. Nothing here counts
attempts or records that work is owed - a pass that failed leaves the two
commits differing, so the next one finds the same work waiting. That
difference *is* the retry, which is why there is no queue to drain, no attempt
column and no backoff to tune.

Backfill and incremental are one code path. An index that has never been built
has nothing to compare against, so everything is considered; one that has
fallen behind considers what changed. Neither is a branch on "is this the
first time" - it is the same call with a different list of paths, and `None`
means all of them.

The pass never waits to be told. A deployment that has received no push
delivery - no tunnel, a webhook nobody configured, a secret that does not
match - has nothing recorded, and asking the repository where its branch is,
is what makes this level-triggered rather than an edge-triggered handler
wearing a reconciler's name. The notification only ever saves the question.
"""

from __future__ import annotations

import logging
import time
from argparse import ArgumentParser
from functools import partial
from typing import Protocol

from argus_core import DatabaseSettings, SettingsSlice, get_settings, open_pool
from argus_core.models import CodeSearch
from argus_core.schema import require_schema
from qdrant_client import QdrantClient
from repository_source import (
    RepositorySourceSettings,
    paths_changed_between,
    the_head_of,
)

from code_index.building import IndexSettings, index_repository
from code_index.embedding import an_embedder
from code_index.records import RepositoryIndex, get

logger = logging.getLogger(__name__)


class ReconcileSettings(SettingsSlice):
    """How often the loop looks, and where it looks.

    The interval is the longest an index may describe yesterday's code while
    nobody is telling it otherwise - a bound on staleness rather than a
    performance knob. Short enough that a push nobody delivered is caught
    within a coffee, long enough that a repository nothing happens to is not
    fetched every minute.
    """

    qdrant_url: str
    code_index_interval_seconds: float
    # Whether this deployment keeps an index at all. A run set to grep alone
    # exits rather than building one nobody can search: the read tier
    # registers no tool for it, so every passage embedded here would be
    # embedded for no caller.
    code_search: CodeSearch


class IndexRecord(Protocol):
    """What is on record about this repository's index, or nothing at all.

    Nothing recorded and an index never built are different absences, and both
    arrive here: the first is a repository nobody has written a row for, the
    second a row whose `indexed_sha` is empty. They call for the same work,
    which is why the decision below reads them the same way.
    """

    def __call__(self) -> RepositoryIndex | None: ...


class BranchHead(Protocol):
    """Where a branch currently points, asked of the provider."""

    def __call__(self, branch: str, /) -> str: ...


class ChangedPaths(Protocol):
    """Which paths differ between two commits, or `None` for "I cannot say".

    The second is not a failure. A provider that will only list the first
    three hundred changed files has given an answer that cannot be told from a
    complete one, and the caller's move for it is to consider everything.
    """

    def __call__(self, base: str, head: str, /) -> list[str] | None: ...


class Pass(Protocol):
    """One reconcile pass, with everything it needs already bound to it."""

    def __call__(self) -> str | None: ...


class Indexer(Protocol):
    """A pass over the repository at a commit, for these paths or for all.

    The seam is the call rather than the store under it: what indexing does is
    `building`'s and is asserted against a real Qdrant there. What belongs
    here is which commit it is aimed at, and with which paths.
    """

    def __call__(self, sha: str, paths: list[str] | None, /) -> None: ...


def reconcile(*,
              settings: IndexSettings,
              recorded: IndexRecord,
              head_of: BranchHead,
              changed_between: ChangedPaths,
              index: Indexer) -> str | None:
    """Closes the gap between what is indexed and what is deployed.

    Answers the commit the index was brought to, or `None` when there was
    nothing to do - which is the ordinary pass, and the one a loop makes most
    of.

    Raises whatever the provider or the store raised. A failure must leave the
    two commits differing: swallowing it would hand the next pass a repository
    that looks reconciled and passages nobody updated.
    """
    on_record = recorded()
    indexed = on_record.indexed_sha if on_record is not None else None
    deployed = _where_the_repository_is(on_record, settings, head_of)

    if indexed == deployed:
        return None

    logger.info("bringing the index from %s up to %s", indexed, deployed)
    index(deployed, _what_to_consider(indexed, deployed, changed_between))

    return deployed


def reconcile_forever(interval_seconds: float,
                      pass_over: Pass) -> None:
    """Reconciles for as long as the process lives, waking on its own schedule.

    A timer rather than a notification, and that is the property worth
    keeping: a reconciler only ever woken by an edge is edge-triggered wearing
    a reconciler's name, and converges only for the deliveries that arrived.
    The webhook shortens the wait and is never load-bearing.

    A pass that raised is logged and slept off rather than ending the process.
    The work it did not do is still described by the difference between the
    two commits, so the next wake-up finds it - where a crash loop would have
    the container restart faster than the provider recovers.
    """
    while True:
        try:
            pass_over()
        except Exception:
            logger.exception("a reconcile pass failed; the gap is left in place")

        time.sleep(interval_seconds)


def _where_the_repository_is(on_record: RepositoryIndex | None,
                             settings: IndexSettings,
                             head_of: BranchHead) -> str:
    """The commit the index is meant to describe.

    What a push reported, where one was, and otherwise what the provider says.
    Asking costs a call and is the only thing that makes a missed delivery a
    delay rather than an index that is never built - and a pass that asked
    even when it had been told would make the notification decorative.
    """
    if on_record is not None and on_record.pending_sha is not None:
        return on_record.pending_sha

    return head_of(settings.github_base_branch)


def _what_to_consider(indexed: str | None,
                      deployed: str,
                      changed_between: ChangedPaths) -> list[str] | None:
    """Which paths this pass reconsiders, or `None` for the whole repository.

    Everything unchanged is already held under an id derived from what it
    says, so a full pass embeds nothing it has seen before - but it asks the
    store once per file to find that out. At forty files that is free; at a
    hundred thousand it is the whole cost of the pass, and this is what turns
    it into the handful that moved.
    """
    if indexed is None:
        return None

    return changed_between(indexed, deployed)


def main(argv: list[str] | None = None) -> None:
    """The process: a pool, a store, a model, then reconcile until killed.

    `--once` makes one pass and exits, which is what a stack runs before the
    services that read the index - in the slot the schema job already
    occupies, and for the same reason: nothing else may be the process that
    has to start first. Without it the first search of a run races the first
    pass, and a suite's answer depends on which won.

    Everything this process needs is built here and nowhere else - the one
    place that knows a pool exists, that Qdrant has an address, or that the
    embedder loads a model. A `main` rather than module-level code, so that
    importing this module starts nothing.

    The schema is checked before the first pass. A reconciler that indexed a
    repository and then found no table to record the commit in would have
    spent the whole build and left the index looking as though it had never
    run.
    """
    logging.basicConfig(level=logging.INFO)

    parser = ArgumentParser(description="Keeps the index describing what is deployed.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="make one pass and exit, rather than reconciling until killed"
    )
    once = parser.parse_args(argv).once

    settings = get_settings()
    index_settings = IndexSettings.of(settings)
    reconcile_settings = ReconcileSettings.of(settings)

    # Before a pool, a store or a model. A deployment searching by grep alone
    # has no reader for any of this, and an index built for nobody costs a
    # repository download and an ONNX runtime to sit unread.
    if reconcile_settings.code_search is CodeSearch.GREP:
        logger.info("no index is kept here: code search is grep alone")

        return

    source_settings = RepositorySourceSettings(
        github_api_url=index_settings.github_api_url,
        github_repository=index_settings.github_repository,
        github_read_token=index_settings.github_read_token
    )
    repository = index_settings.github_repository

    # The client is closed in a `finally` rather than a `with`: it holds a
    # session like a pool does, and unlike a pool it is not a context manager.
    store = QdrantClient(url=reconcile_settings.qdrant_url)

    with open_pool(DatabaseSettings.of(settings)) as pool:
        with pool.connection() as conn:
            require_schema(conn)

        embed = an_embedder()

        def pass_over() -> str | None:
            """One pass, with a connection of its own.

            Per pass rather than held for the life of the loop: most passes
            find nothing to do and end in seconds, and a connection kept open
            between them is one the pool cannot give to anybody else while
            this process sleeps.
            """
            with pool.connection() as conn:
                return reconcile(
                    settings=index_settings,
                    recorded=partial(get, conn, repository),
                    head_of=partial(the_head_of, settings=source_settings),
                    changed_between=partial(
                        paths_changed_between, settings=source_settings
                    ),
                    index=lambda sha, paths: index_repository(
                        repository,
                        sha,
                        settings=index_settings,
                        conn=conn,
                        store=store,
                        embed=embed,
                        paths=paths
                    )
                )

        logger.info("reconciling the index of %s", repository)

        try:
            if once:
                pass_over()
            else:
                reconcile_forever(
                    reconcile_settings.code_index_interval_seconds, pass_over
                )
        finally:
            store.close()


if __name__ == "__main__":
    main()
