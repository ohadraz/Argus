"""The push that tells Argus its index of the service's source is behind (§11).

The edge in an edge-triggered notification, level-triggered reconciliation
pair. It records that the repository has moved and does no work of its own:
the catch-up pass compares what is recorded here with what the index describes
and closes the gap, so a delivery that never arrives costs a delay rather than
a permanently stale index.

It cannot do the work even if it wanted to. `web_app` serves HTML without
installing an agent, and indexing here would put an ONNX runtime and a
vector-store client into the process that renders a page - the same argument
the alert webhook already makes about walking an incident.

Which host sent it, and how it proves so, is the push source's: this is handed
a push already verified, in git's own terms, and decides only whether it is
news - for a deployment that keeps an index, of the branch that is deployed,
in the repository that is indexed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final, Protocol

from core import SettingsSlice
from core.models import CodeSearch
from push_source import PushSource

logger = logging.getLogger(__name__)

# What a branch's ref looks like, in full. Matched as a prefix rather than by
# taking the last segment: a tag named `main` is `refs/tags/main`, and a
# comparison against the segment alone would index a tag as though somebody
# had deployed it.
BRANCH_REF_PREFIX: Final = "refs/heads/"


class PushSettings(SettingsSlice):
    """What this endpoint is allowed to know: who it trusts, and what it watches.

    No credential that reads or writes a repository. Nothing here fetches
    anything - it is handed what happened and writes one string - and a slice
    naming a token would be giving the web process a capability it has no use
    for.
    """

    github_repository: str
    deployed_branch: str
    # The shared secret GitHub signs each delivery with, handed to the push
    # source where the app is wired. Empty is not a deployment that accepts
    # anything: where no secret is set every delivery is refused - a digest
    # under an empty key is one anybody can compute - which is the right way
    # round for an endpoint open to the internet.
    github_webhook_secret: str
    # Whether this deployment keeps an index for the row to be about. Where it
    # does not, nothing ever reads what is written here - the read tier
    # registers no tool to search an index and the catch-up pass exits before
    # it opens a store - and a mechanism switched off everywhere but its
    # bookkeeping is one that leaves rows nobody can account for.
    code_search: CodeSearch


class Watermark(Protocol):
    """How this endpoint says where the repository now is.

    A seam rather than the write itself, because the row belongs to the index
    and is asserted against a real database there. What belongs here is which
    pushes reach it at all.
    """

    def __call__(self, repository: str, sha: str, /) -> None: ...


def receive_push(body: bytes,
                 headers: Mapping[str, str],
                 *,
                 settings: PushSettings,
                 source: PushSource,
                 record_pushed: Watermark) -> str | None:
    """Records the commit a verified push moved the deployed branch to.

    Answers the commit it recorded, or `None` for a push there was nothing to
    record about - another branch, a tag, another repository, a delivery that
    is no push, or a deployment that keeps no index at all. All are accepted
    deliveries: the host is told the delivery was received either way, because
    a webhook that answers an error for news it simply does not need is a
    webhook somebody eventually disables.

    Raises `PushUnverified` when the source cannot vouch for the delivery.
    Asked first, and over the raw body and its headers, which is why this
    takes `bytes` rather than a parsed payload: re-serializing a document to
    verify it is verifying a different document.
    """
    push = source.parse_delivery(body, headers)

    if push is None or settings.code_search is CodeSearch.GREP:
        return None

    if not _is_the_deployed_branch(push.ref, settings):
        return None

    if not _is_the_indexed_repository(push.repository, settings):
        return None

    record_pushed(settings.github_repository, push.after)

    logger.info("push recorded", extra={"repository": push.repository, "sha": push.after})

    return push.after


def _is_the_deployed_branch(ref: str, settings: PushSettings) -> bool:
    """Whether this push moved the branch that is actually running.

    A push to anything else changes nothing about what is deployed, and
    recorded it would have the index chase a commit running nowhere while
    reporting itself current.
    """
    return ref == f"{BRANCH_REF_PREFIX}{settings.deployed_branch}"


def _is_the_indexed_repository(repository: str, settings: PushSettings) -> bool:
    """Whether this push is about the repository this deployment indexes.

    A webhook pointed at the wrong deployment is answered as received and
    recorded nowhere, so it is said: it would otherwise look exactly like one
    that works.
    """
    if repository != settings.github_repository:
        logger.warning("push for another repository", extra={"repository": repository})
        return False

    return True
