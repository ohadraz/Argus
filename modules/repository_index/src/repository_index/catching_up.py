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

Named for catching up rather than for reconciling, because Argo CD reconciles
the Target Service's deployment and the two are different mechanisms sharing
one word. Catching up is also the truer verb for a single pass: most passes
find the two commits equal and answer `None`, where a name promising work
every call would describe the rare pass rather than the ordinary one.

The process that runs the loop - its pool, the code host, the store, the
embedder - is built by its root, `apps.indexer`, and every pass is handed what
it reads as a port.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from repository_index.building import IndexSettings
from repository_index.records import RepositoryIndex

logger = logging.getLogger(__name__)

# How the wait between passes is spent. Injected so that a loop which never
# returns can still be driven by a test, through a sleep that ends it.
Sleeper = Callable[[float], None]


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
    """One catch-up pass, with everything it needs already bound to it."""

    def __call__(self) -> str | None: ...


class Indexer(Protocol):
    """A pass over the repository at a commit, for these paths or for all.

    The seam is the call rather than the store under it: what indexing does is
    `building`'s and is asserted against a real Qdrant there. What belongs
    here is which commit it is aimed at, and with which paths.
    """

    def __call__(self, sha: str, paths: list[str] | None, /) -> None: ...


def catch_up(*,
             settings: IndexSettings,
             recorded: IndexRecord,
             head_of: BranchHead,
             changed_between: ChangedPaths,
             index: Indexer) -> str | None:
    """Closes the gap between what is indexed and what is deployed.

    Answers the commit the index was brought to, or `None` when there was
    nothing to catch up on - which is the ordinary pass, and the one a loop
    makes most of.

    Raises whatever the provider or the store raised. A failure must leave the
    two commits differing: swallowing it would hand the next pass a repository
    that looks caught up and passages nobody updated.
    """
    on_record = recorded()
    indexed = on_record.indexed_sha if on_record is not None else None
    deployed = _where_the_repository_is(on_record, settings, head_of)

    if indexed == deployed:
        return None

    index(deployed, _what_to_consider(indexed, deployed, changed_between))

    logger.info("index brought up to date", extra={"from_sha": indexed, "to_sha": deployed})

    return deployed


def catch_up_forever(interval_seconds: float,
                     pass_over: Pass,
                     *,
                     sleep: Sleeper = time.sleep) -> None:
    """Catches up for as long as the process lives, waking on its own schedule.

    A timer rather than a notification, and that is the property worth
    keeping: a reconciler only ever woken by an edge is edge-triggered wearing
    a reconciler's name, and converges only for the deliveries that arrived.
    The webhook shortens the wait and is never load-bearing.

    A pass that raised is logged and slept off rather than ending the process.
    The work it did not do is still described by the difference between the
    two commits, so the next wake-up finds it - where a crash loop would have
    the container restart faster than the provider recovers. A warning rather
    than an error for the same reason: nobody has to act, because the next pass
    is the retry.
    """
    while True:
        try:
            pass_over()
        except Exception:
            logger.warning("catch-up pass failed", exc_info=True)

        sleep(interval_seconds)


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

    return head_of(settings.deployed_branch)


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
        logger.info("whole index build started", extra={"to_sha": deployed})
        return None

    changed = changed_between(indexed, deployed)

    if changed is None:
        logger.warning("comparison incomplete, considering everything",
                       extra={"from_sha": indexed, "to_sha": deployed})

    return changed
