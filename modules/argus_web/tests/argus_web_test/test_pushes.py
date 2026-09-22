"""The push that tells Argus its index is behind (spec §11).

The edge in an edge-triggered notification, level-triggered reconciliation
pair: this records that the repository has moved and does no work of its own.
It cannot - `argus_web` serves HTML without installing an agent, and indexing
here would put an ONNX runtime and a vector-store client into the process that
renders a page.

What it must get right is the order. GitHub signs the delivery, and the
signature covers the bytes that arrived rather than anything parsed out of
them, so verification comes before the body is read at all: a payload that was
decoded, validated and only then checked is a payload that already ran through
a parser on an unauthenticated caller's say-so.

Everything else it does is refuse. A push to a branch nobody deploys changes
nothing about what is running, and a push to a repository Argus does not index
is somebody else's news.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import CodeSearch
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.scenario import Scenario, attempting
from argus_web.pushes import (
    PushSettings,
    PushUnverified,
    Watermark,
    receive_push,
)

THE_REPOSITORY = "ohadraz/Argus-Demo-Target-App"
THE_DEPLOYED_BRANCH = "main"
THE_COMMIT_PUSHED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

SOME_SECRET = "a-webhook-secret"
DONT_CARE_SECRET = "dont-care-secret"


@pytest.mark.unit
def test_a_signed_push_records_the_commit_it_names_as_the_one_to_catch_up_to() -> None:
    # The whole of what the webhook does. The difference between this commit
    # and the one the index describes is the work list, the retry and the
    # staleness signal at once - so recording it is recording all three.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(SOME_SECRET, after=THE_COMMIT_PUSHED)

    Scenario() \
        .when(
            lambda: receive_push(
                body,
                signature,
                settings=some_settings(secret=SOME_SECRET),
                record_pushed=watermark
            )
        ) \
        .then(
            all_of(
                _what_was_recorded_is(watermark, THE_REPOSITORY, THE_COMMIT_PUSHED),
                the_answer_was(THE_COMMIT_PUSHED)
            )
        )


@pytest.mark.unit
def test_an_unsigned_delivery_is_refused_and_records_nothing() -> None:
    # This endpoint is open to the internet and the only state it can move is
    # one string in one row - but that string is what the index chases, and an
    # unauthenticated caller who can set it can make Argus report a current
    # index as permanently behind.
    watermark = a_watermark()
    body, _ = a_delivery_signed_with(SOME_SECRET)

    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    body,
                    None,
                    settings=some_settings(secret=SOME_SECRET),
                    record_pushed=watermark
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(PushUnverified),
                _nothing_was_recorded(watermark)
            )
        )


@pytest.mark.unit
def test_a_delivery_signed_with_the_wrong_secret_is_refused() -> None:
    watermark = a_watermark()
    body, signature = a_delivery_signed_with("not-the-secret")

    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    body,
                    signature,
                    settings=some_settings(secret=SOME_SECRET),
                    record_pushed=watermark
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(PushUnverified),
                _nothing_was_recorded(watermark)
            )
        )


@pytest.mark.unit
def test_a_signature_over_different_bytes_than_arrived_is_refused() -> None:
    # The signature covers what was sent, byte for byte. A body re-serialized
    # on the way in - a key reordered, a space added - is a different document
    # and has a different digest, which is why nothing may parse it first and
    # verify the result.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(SOME_SECRET)

    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    body + b" ",
                    signature,
                    settings=some_settings(secret=SOME_SECRET),
                    record_pushed=watermark
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(PushUnverified),
                _nothing_was_recorded(watermark)
            )
        )


@pytest.mark.unit
def test_an_unsigned_delivery_is_refused_before_its_body_is_read() -> None:
    # The order is the security property. A payload decoded, validated and
    # only then checked is a payload that ran through a parser on an
    # unauthenticated caller's say-so - so a body that is not even JSON must
    # come back as a refused signature rather than as a parse error.
    watermark = a_watermark()

    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    b"not json at all",
                    None,
                    settings=some_settings(secret=SOME_SECRET),
                    record_pushed=watermark
                )
            )
        ) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_push_to_a_branch_nobody_deploys_records_nothing() -> None:
    # Recorded, the index would chase a commit that is not running anywhere -
    # and every search by meaning would answer passages from somebody's
    # feature branch while reporting itself current.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(
        SOME_SECRET, ref="refs/heads/a-feature-branch"
    )

    Scenario() \
        .when(
            lambda: receive_push(
                body,
                signature,
                settings=some_settings(secret=SOME_SECRET),
                record_pushed=watermark
            )
        ) \
        .then(
            all_of(
                _nothing_was_recorded(watermark),
                the_answer_was(None)
            )
        )


@pytest.mark.unit
def test_a_tag_or_anything_that_is_not_a_branch_records_nothing() -> None:
    # A tag whose name happens to match the deployed branch is not that
    # branch, and a comparison against the last path segment would say it was.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(
        SOME_SECRET, ref=f"refs/tags/{THE_DEPLOYED_BRANCH}"
    )

    Scenario() \
        .when(
            lambda: receive_push(
                body,
                signature,
                settings=some_settings(secret=SOME_SECRET),
                record_pushed=watermark
            )
        ) \
        .then(_nothing_was_recorded(watermark))


@pytest.mark.unit
def test_a_push_to_a_repository_argus_does_not_index_records_nothing() -> None:
    # One deployment indexes one repository. A row written for another is work
    # the catch-up pass will pick up and a repository it has no credential to
    # read - and a webhook pointed somewhere by mistake should be inert rather
    # than quietly productive.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(
        SOME_SECRET, repository="someone-else/their-service"
    )

    Scenario() \
        .when(
            lambda: receive_push(
                body,
                signature,
                settings=some_settings(secret=SOME_SECRET),
                record_pushed=watermark
            )
        ) \
        .then(_nothing_was_recorded(watermark))


@pytest.mark.unit
def test_a_deployment_that_keeps_no_index_records_nothing() -> None:
    # Nothing reads this row where there is no index: the read tier registers
    # no tool to search one and the catch-up pass exits before it opens a store.
    # Written anyway, it is a row kept current for nobody - and the one thing
    # worse than a setting that switches a mechanism off is one that switches
    # off all of it but the bookkeeping.
    watermark = a_watermark()
    body, signature = a_delivery_signed_with(SOME_SECRET)

    Scenario() \
        .when(
            lambda: receive_push(
                body,
                signature,
                settings=some_settings(
                    secret=SOME_SECRET, code_search=CodeSearch.GREP
                ),
                record_pushed=watermark
            )
        ) \
        .then(
            all_of(
                _nothing_was_recorded(watermark),
                the_answer_was(None)
            )
        )


def _what_was_recorded_is(watermark: Any,
                          repository: str,
                          sha: str) -> Assertion[Any]:
    """The repository and the commit it is now at, as the row is keyed."""
    def assertion(dont_care_result: Any) -> bool:
        recorded = watermark.call_args

        if recorded is None or recorded.args != (repository, sha):
            raise AssertionError(
                f"Expected [{repository}] recorded at [{sha}], got [{recorded}]."
            )

        return True

    return assertion


def _nothing_was_recorded(watermark: Any) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if watermark.call_args_list:
            raise AssertionError(
                f"Expected nothing recorded, got {watermark.call_args_list}."
            )

        return True

    return assertion


def a_watermark() -> Any:
    """A stand-in for the row this writes.

    The seam is the write rather than the connection under it: what the row
    does is `code_index`'s and is asserted there against a real database, and
    what belongs here is which pushes reach it at all.
    """
    return create_autospec(Watermark, instance=True)


def a_delivery_signed_with(secret: str,
                           repository: str = THE_REPOSITORY,
                           ref: str = f"refs/heads/{THE_DEPLOYED_BRANCH}",
                           after: str = THE_COMMIT_PUSHED) -> tuple[bytes, str]:
    """A push delivery as GitHub sends one: the bytes, and the header over them.

    Built here rather than fixtured, because the signature is over exactly
    these bytes - a helper that returned a dict and let the caller serialize it
    would be a helper that signs a different document than it hands over.
    """
    body = json.dumps({
        "ref": ref,
        "after": after,
        "repository": {"full_name": repository}
    }).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return body, f"sha256={digest}"


def some_settings(secret: str = DONT_CARE_SECRET,
                  repository: str = THE_REPOSITORY,
                  base_branch: str = THE_DEPLOYED_BRANCH,
                  code_search: CodeSearch = CodeSearch.BOTH) -> PushSettings:
    """What the webhook is allowed to know: who it trusts, and what it watches.

    `code_search` is whether this deployment keeps an index at all. Both by
    default, because the tests that care say so and the rest are about which
    pushes are worth recording in the first place.
    """
    return PushSettings(
        github_repository=repository,
        github_base_branch=base_branch,
        github_webhook_secret=secret,
        code_search=code_search
    )
