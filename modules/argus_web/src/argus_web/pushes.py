"""The push that tells Argus its index of the service's source is behind (§11).

The edge in an edge-triggered notification, level-triggered reconciliation
pair. It records that the repository has moved and does no work of its own: the
reconciler compares what is recorded here with what the index describes and
closes the gap, so a delivery that never arrives costs a delay rather than a
permanently stale index.

It cannot do the work even if it wanted to. `argus_web` serves HTML without
installing an agent, and indexing here would put an ONNX runtime and a
vector-store client into the process that renders a page - the same argument
the alert webhook already makes about walking an incident.

Order is the whole of the security here. GitHub signs the bytes it sent, not
anything parsed out of them, so the signature is checked before the body is
read at all: a payload decoded, validated and only then verified is a payload
that ran through a parser on an unauthenticated caller's say-so.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Final, Protocol

from argus_core import SettingsSlice
from argus_core.models import CodeSearch

# GitHub's wire vocabulary for a push, named for the fields that carry it.
# `AFTER_FIELD` is the load-bearing one: it is the commit the branch now
# points at, which is the whole of what this endpoint exists to record.
REF_FIELD: Final = "ref"
AFTER_FIELD: Final = "after"
REPOSITORY_FIELD: Final = "repository"
FULL_NAME_FIELD: Final = "full_name"

# What a branch's ref looks like, in full. Matched as a prefix rather than by
# taking the last segment: a tag named `main` is `refs/tags/main`, and a
# comparison against the segment alone would index a tag as though somebody
# had deployed it.
BRANCH_REF_PREFIX: Final = "refs/heads/"

# The header the delivery is signed in, and how that signature is spelled.
SIGNATURE_HEADER: Final = "X-Hub-Signature-256"
SIGNATURE_PREFIX: Final = "sha256="


class PushUnverified(Exception):
    """The delivery did not come from GitHub, or did not arrive intact.

    Raised rather than answered quietly, because the two things this endpoint
    can do are record a commit and refuse - and a refusal that looked like an
    accepted push would leave whoever configured the webhook believing the
    index is being told about their work.
    """


class PushSettings(SettingsSlice):
    """What this endpoint is allowed to know: who it trusts, and what it watches.

    No credential that reads or writes a repository. Nothing here fetches
    anything - it is handed what happened and writes one string - and a slice
    naming a token would be giving the web process a capability it has no use
    for.
    """

    github_repository: str
    github_base_branch: str
    # The shared secret GitHub signs each delivery with. Empty is not a
    # deployment that accepts anything: with no secret configured no signature
    # can match, so every delivery is refused, which is the right way round for
    # an endpoint open to the internet.
    github_webhook_secret: str
    # Whether this deployment keeps an index for the row to be about. Where it
    # does not, nothing ever reads what is written here - the read tier
    # registers no tool to search an index and the reconciler exits before it
    # opens a store - and a mechanism switched off everywhere but its
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
                 signature: str | None,
                 *,
                 settings: PushSettings,
                 record_pushed: Watermark) -> str | None:
    """Records the commit a verified push moved the deployed branch to.

    Answers the commit it recorded, or `None` for a push there was nothing to
    record about - another branch, a tag, another repository, or a deployment
    that keeps no index at all. All are accepted deliveries: GitHub is told
    the delivery was received either way, because a webhook that answers an
    error for news it simply does not need is a webhook somebody eventually
    disables.

    Raises `PushUnverified` when the signature is absent or does not match the
    bytes that arrived. Checked first, and against the raw body, which is why
    this takes `bytes` rather than a parsed payload: re-serializing a document
    to verify it is verifying a different document.
    """
    _verified(body, signature, settings)

    if settings.code_search is CodeSearch.GREP:
        return None

    push = json.loads(body)

    if not _is_the_deployed_branch(str(push.get(REF_FIELD, "")), settings):
        return None

    if _the_repository_of(push) != settings.github_repository:
        return None

    sha = str(push[AFTER_FIELD])
    record_pushed(settings.github_repository, sha)

    return sha


def _verified(body: bytes,
              signature: str | None,
              settings: PushSettings) -> None:
    """That these bytes were signed with the secret, or the refusal that they
    were not.

    `compare_digest` rather than `==`: a comparison that returns early on the
    first wrong byte tells an attacker how much of a guess was right, and a
    signature can be guessed a byte at a time by anybody who can time the
    answer.
    """
    expected = SIGNATURE_PREFIX + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if signature is None or not hmac.compare_digest(expected, signature):
        raise PushUnverified(
            "the delivery is not signed with this deployment's webhook secret"
        )


def _is_the_deployed_branch(ref: str, settings: PushSettings) -> bool:
    """Whether this push moved the branch that is actually running.

    A push to anything else changes nothing about what is deployed, and
    recorded it would have the index chase a commit running nowhere while
    reporting itself current.
    """
    return ref == f"{BRANCH_REF_PREFIX}{settings.github_base_branch}"


def _the_repository_of(push: dict[str, Any]) -> str:
    """Which repository the delivery is about, as it names itself."""
    repository = push.get(REPOSITORY_FIELD) or {}

    return str(repository.get(FULL_NAME_FIELD, ""))
