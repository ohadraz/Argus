"""What a push to the service's repository does to Argus's index of it (§11).

An edge-triggered notification, level-triggered reconciliation pair, and both
halves are here. `argus_web` verifies the delivery and writes down the commit
the branch moved to - that and nothing else, because indexing in the process
that serves a page would install an ONNX runtime to render HTML. The reconciler
sees the two commits differ and closes the gap.

So the wait in the second assertion is the point rather than an inconvenience:
what is being tested is that a push shortens a delay, not that it does the
work. A delivery that never arrives costs a stale index until the next pass, and
one that arrives signed by nobody costs nothing at all.

Both cases push a commit that exists and that no branch points at. It has to be
real, because the reconciler goes and reads it: a fabricated sha would have the
pass fail on a repository that has no such commit, and the case would then be
asserting the retry rather than the catch-up.

Not collected where this deployment keeps no index. Under `CODE_SEARCH=grep` the
endpoint records nothing, the reconciler exits before it opens a store, and
there is no watermark for a push to move - so the session leaves this file out
rather than the file skipping itself. A skip is a result, and two of them on
every run teach a reader to read past the line that will one day say something
else.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any, Final

import httpx
import psycopg
import pytest
from argus_core import get_settings
from argus_testkit import Assertion, Scenario, all_of, eventually
from argus_web.pushes import (
    AFTER_FIELD,
    BRANCH_REF_PREFIX,
    FULL_NAME_FIELD,
    REF_FIELD,
    REPOSITORY_FIELD,
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
)
from code_index.records import RepositoryIndex
from code_index.records import get as the_index_recorded_for
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    argus_returns_status,
)

PUSH_WEBHOOK_PATH = "/webhooks/github/push"

# A file the fixture repository does not have, inside the scope the deployment
# indexes - so the comparison the reconciler makes has something in it, and what
# it embeds is a passage it has never seen.
A_FILE_THE_REPOSITORY_DID_NOT_HAVE: Final = "src/io_shop/refunds.py"
SOME_SOURCE: Final = (
    "def refund_in_cents(order):\n"
    "    return sum(line.price_cents for line in order.lines)\n"
)

# How long the reconciler is given to notice and close the gap. Several of its
# own intervals plus room for the pass itself: a push can arrive the moment a
# pass went to sleep, so one interval is the wait before it even looks.
THE_INDEX_CATCHES_UP_SECONDS: Final = int(
    get_settings().code_index_interval_seconds * 3 + 60
)


@pytest.mark.e2e
def test_a_signed_push_moves_the_watermark_and_the_index_follows_it() -> None:
    Scenario() \
        .given(
            pushed := _a_commit_the_deployed_branch_does_not_point_at()
        ) \
        .when(
            _a_signed_push_of(pushed)
        ) \
        .then(
            all_of(
                argus_returns_status(HttpStatus.ACCEPTED),
                _the_delivery_reported_recording(pushed),
                _the_watermark_points_at(pushed)
            ),
            # The other half, and the slow one: nothing above proves the index
            # is anything but a row saying it is behind.
            eventually(
                _the_stored_passages_describe(pushed),
                timeout=THE_INDEX_CATCHES_UP_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_push_nobody_signed_moves_nothing() -> None:
    # The endpoint is open to the internet, which is the whole of why this case
    # exists: anybody can post a push, and what stops an unsigned one aiming the
    # index at a commit of their choosing is a signature checked over the bytes
    # that arrived, before the body is parsed at all.
    Scenario() \
        .given(
            some_commit := _a_commit_the_deployed_branch_does_not_point_at()
        ) \
        .when(
            _an_unsigned_push_of(some_commit)
        ) \
        .then(
            all_of(
                argus_returns_status(HttpStatus.UNAUTHORIZED),
                _nothing_was_recorded_about(some_commit)
            )
        )


def _the_delivery_reported_recording(sha: str) -> Assertion[httpx.Response]:
    """The endpoint's own answer, which is what GitHub would see.

    Asserted beside the row because the two can disagree in the direction that
    matters: a delivery filtered out for being about another branch is a `202`
    carrying nothing, and it looks exactly like a recorded push from the outside.
    """
    def assertion(response: httpx.Response) -> bool:
        recorded = response.json().get("recorded")

        if recorded != sha:
            raise AssertionError(
                f"Expected the push of [{sha}] to be recorded, and the webhook "
                f"answered [{recorded!r}]."
            )

        return True

    return assertion


def _the_watermark_points_at(sha: str) -> Assertion[Any]:
    """Where the repository is, as the row says it - written before the reply.

    Not `eventually`: the endpoint writes this in the request, so a row that is
    not there by now is not late, it is absent.
    """
    def assertion(_: Any) -> bool:
        recorded = _what_the_index_records()

        if recorded is None:
            raise AssertionError(
                f"Nothing is recorded about "
                f"[{get_settings().github_repository}] at all, so the push "
                f"was verified and then written nowhere."
            )

        if recorded.pending_sha != sha:
            raise AssertionError(
                f"Expected the repository to be recorded at [{sha}], and the "
                f"row says [{recorded.pending_sha!r}]."
            )

        return True

    return assertion


def _the_stored_passages_describe(sha: str) -> Assertion[Any]:
    """The index caught up with what it was told, by its own account.

    `indexed_sha` rather than a search for the new file: what a passage says is
    `code_index`'s own suite's subject, asserted there against a real store. What
    this case is about is the pair converging - a notification the reconciler
    acted on, rather than one it recorded and left.
    """
    def assertion(_: Any) -> bool:
        recorded = _what_the_index_records()

        if recorded is None or recorded.indexed_sha != sha:
            raise AssertionError(
                f"Expected the index to describe [{sha}], and it describes "
                f"[{recorded.indexed_sha if recorded else None!r}]."
            )

        return True

    return assertion


def _nothing_was_recorded_about(sha: str) -> Assertion[Any]:
    """The refusal left the watermark wherever it was.

    Said as "not this commit" rather than "unchanged", because the row is
    rebuilt by whichever reconcile pass runs next and comparing it with what it
    held a moment ago would be asserting the reconciler's timing. What must
    never be true is that an unsigned caller's commit is in it.
    """
    def assertion(_: Any) -> bool:
        recorded = _what_the_index_records()

        if recorded is not None and recorded.pending_sha == sha:
            raise AssertionError(
                f"An unsigned push aimed the index at [{sha}], so the signature "
                f"is not what decides whether a delivery is believed."
            )

        return True

    return assertion


def _what_the_index_records() -> RepositoryIndex | None:
    with psycopg.connect(DATABASE_URL) as conn:
        return the_index_recorded_for(conn, get_settings().github_repository)


def _a_signed_push_of(sha: str) -> Callable[[], httpx.Response]:
    """The delivery as GitHub sends it, signed with the secret it was given."""
    def step() -> httpx.Response:
        body = _a_push_naming(sha)

        return httpx.post(
            f"{ARGUS_WEB_BASE_URL}{PUSH_WEBHOOK_PATH}",
            content=body,
            headers={SIGNATURE_HEADER: _the_signature_over(body)},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

    return step


def _an_unsigned_push_of(sha: str) -> Callable[[], httpx.Response]:
    """The same delivery from somebody who does not have the secret."""
    def step() -> httpx.Response:
        return httpx.post(
            f"{ARGUS_WEB_BASE_URL}{PUSH_WEBHOOK_PATH}",
            content=_a_push_naming(sha),
            timeout=REQUEST_TIMEOUT_SECONDS
        )

    return step


def _a_push_naming(sha: str) -> bytes:
    """A push payload, as bytes, because bytes are what is signed.

    Serialized once and both signed and sent, for the reason the endpoint reads
    the raw body: a document re-serialized between the two is a different
    document, and a signature over it would verify nothing about what arrived.
    """
    settings = get_settings()

    return json.dumps({
        REF_FIELD: f"{BRANCH_REF_PREFIX}{settings.github_base_branch}",
        AFTER_FIELD: sha,
        REPOSITORY_FIELD: {FULL_NAME_FIELD: settings.github_repository}
    }).encode()


def _the_signature_over(body: bytes) -> str:
    return SIGNATURE_PREFIX + hmac.new(
        get_settings().github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()


def _a_commit_the_deployed_branch_does_not_point_at() -> str:
    """A real commit, one file ahead of what is deployed, on no branch at all.

    Written through the repository's own API rather than staged in a fixture,
    because the reconciler reads it back the same way: a commit the provider
    cannot serve is a pass that fails, and this case would then be waiting for a
    retry it never asked about.

    On no branch, deliberately. What the reconciler follows is the commit it was
    told about, and a push that also moved `main` could not tell that apart from
    it asking the provider where the branch is.
    """
    head = _the_commit_the_deployed_branch_points_at()

    return _a_commit_on(
        _a_tree_over(_the_tree_of(head), A_FILE_THE_REPOSITORY_DID_NOT_HAVE, SOME_SOURCE),
        parent=head
    )


def _the_commit_the_deployed_branch_points_at() -> str:
    return str(
        _the_repository_answered(
            "get", f"/git/ref/heads/{get_settings().github_base_branch}"
        )["object"]["sha"]
    )


def _the_tree_of(commit: str) -> str:
    return str(_the_repository_answered("get", f"/git/commits/{commit}")["tree"]["sha"])


def _a_tree_over(base_tree: str, path: str, content: str) -> str:
    return str(
        _the_repository_answered(
            "post",
            "/git/trees",
            {"base_tree": base_tree, "tree": [{"path": path, "content": content}]}
        )["sha"]
    )


def _a_commit_on(tree: str, parent: str) -> str:
    return str(
        _the_repository_answered(
            "post", "/git/commits", {"tree": tree, "parents": [parent]}
        )["sha"]
    )


def _the_repository_answered(method: str,
                             path: str,
                             asked: dict[str, Any] | None = None) -> dict[str, Any]:
    """One call to the repository Argus is pointed at, which for a suite is the
    double - the same address the read and write tiers use, so a case cannot be
    arranging one repository while Argus reads another."""
    response = httpx.request(
        method,
        f"{GITHUB_DOUBLE_BASE_URL}/repos/{get_settings().github_repository}{path}",
        json=asked,
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    answered: dict[str, Any] = response.json()

    return answered
