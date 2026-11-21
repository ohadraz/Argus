"""The push that tells Argus its index is behind (spec §11).

The edge in an edge-triggered notification, level-triggered reconciliation
pair: this records that the repository has moved and does no work of its own.
It cannot - `web_app` serves HTML without installing an agent, and indexing
here would put an ONNX runtime and a vector-store client into the process that
renders a page.

Who sent the push, and whether it can be trusted, is the push source's: it is
handed the bytes that arrived and their headers, and answers a push already
verified, or refuses. What is left here is refusing everything that is not
news - a push to a branch nobody deploys changes nothing about what is running,
and a push to a repository Argus does not index is somebody else's news.
"""

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.logs import one_record_was_logged
from argus_testkit.scenario import Scenario, attempting, calling
from core.models import CodeSearch
from push_source import Pushed, PushSource, PushUnverified
from web_app.pushes import (
    PushSettings,
    Watermark,
    receive_push,
)

THE_REPOSITORY = "ohadraz/Argus-Demo-Target-App"
THE_DEPLOYED_BRANCH = "main"
THE_COMMIT_PUSHED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

DONT_CARE_SECRET = "dont-care-secret"

SOME_BODY = b'{"some": "delivery"}'
SOME_HEADERS = {"some-header": "some-value"}


@pytest.mark.unit
def test_a_verified_push_records_the_commit_it_names_as_the_one_to_catch_up_to() -> None:
    # The whole of what the webhook does. The difference between this commit
    # and the one the index describes is the work list, the retry and the
    # staleness signal at once - so recording it is recording all three.
    watermark = a_watermark()

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(after=THE_COMMIT_PUSHED)),
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
def test_the_source_is_handed_the_bytes_that_arrived_and_their_headers() -> None:
    # The signature is over exactly these bytes, and travels in a header - so
    # nothing may parse the body first and hand on the result.
    source = a_source_saying(a_push())

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=source,
                record_pushed=a_watermark()
            )
        ) \
        .then(_the_source_was_handed(source, SOME_BODY, SOME_HEADERS))


@pytest.mark.unit
def test_a_delivery_the_source_cannot_vouch_for_is_refused_and_records_nothing() -> None:
    # This endpoint is open to the internet and the only state it can move is
    # one string in one row - but that string is what the index chases, and an
    # unauthenticated caller who can set it can make Argus report a current
    # index as permanently behind.
    watermark = a_watermark()

    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    SOME_BODY,
                    SOME_HEADERS,
                    settings=some_settings(),
                    source=a_source_refusing(),
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
def test_a_delivery_that_is_no_push_records_nothing() -> None:
    # The host checking the address it was given, when the webhook is created:
    # received intact, and news of nothing.
    watermark = a_watermark()

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(None),
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
def test_a_push_to_a_branch_nobody_deploys_records_nothing() -> None:
    # Recorded, the index would chase a commit that is not running anywhere -
    # and every search by meaning would answer passages from somebody's
    # feature branch while reporting itself current.
    watermark = a_watermark()

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(ref="refs/heads/a-feature-branch")),
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

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(ref=f"refs/tags/{THE_DEPLOYED_BRANCH}")),
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

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(repository="someone-else/their-service")),
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

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(code_search=CodeSearch.GREP),
                source=a_source_saying(a_push()),
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
def test_a_deployment_that_keeps_no_index_still_refuses_a_delivery_it_cannot_trust() -> None:
    # Whatever the deployment keeps, an endpoint open to the internet answers
    # an unverified caller with a refusal, never with "received".
    Scenario() \
        .when(
            attempting(
                lambda: receive_push(
                    SOME_BODY,
                    SOME_HEADERS,
                    settings=some_settings(code_search=CodeSearch.GREP),
                    source=a_source_refusing(),
                    record_pushed=a_watermark()
                )
            )
        ) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_push_recorded_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # The commit the index is now chasing, said where a person looking for why
    # it is behind will look first.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO))
        ) \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(after=THE_COMMIT_PUSHED)),
                record_pushed=a_watermark()
            )
        ) \
        .then(
            one_record_was_logged(caplog, "web_app.pushes", logging.INFO,
                                  "push recorded",
                                  values={"repository": THE_REPOSITORY,
                                          "sha": THE_COMMIT_PUSHED})
        )


@pytest.mark.unit
def test_a_push_to_a_repository_argus_does_not_index_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Answered as received and recorded nowhere, so a webhook pointed at the
    # wrong deployment would otherwise look exactly like one that works.
    some_other_repository = "someone-else/their-service"

    Scenario() \
        .when(
            lambda: receive_push(
                SOME_BODY,
                SOME_HEADERS,
                settings=some_settings(),
                source=a_source_saying(a_push(repository=some_other_repository)),
                record_pushed=a_watermark()
            )
        ) \
        .then(
            one_record_was_logged(caplog, "web_app.pushes", logging.WARNING,
                                  "push for another repository",
                                  values={"repository": some_other_repository})
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


def _the_source_was_handed(source: Any, body: bytes, headers: dict[str, str]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        handed = source.parse_delivery.call_args

        if handed is None or handed.args != (body, headers):
            raise AssertionError(
                f"Expected the source handed [{body!r}] with {headers}, got [{handed}]."
            )

        return True

    return assertion


def a_watermark() -> Any:
    """A stand-in for the row this writes.

    The seam is the write rather than the connection under it: what the row
    does is `repository_index`'s and is asserted there against a real database, and
    what belongs here is which pushes reach it at all.
    """
    return create_autospec(Watermark, instance=True)


def a_push(repository: str = THE_REPOSITORY,
           ref: str = f"refs/heads/{THE_DEPLOYED_BRANCH}",
           after: str = THE_COMMIT_PUSHED) -> Pushed:
    """A push as a source answers one once it has verified it: by default, to
    the deployed branch of the indexed repository."""
    return Pushed(repository=repository, ref=ref, after=after)


def a_source_saying(push: Pushed | None) -> PushSource:
    """A source that vouches for every delivery, and reads each as `push`."""
    source = create_autospec(PushSource, instance=True)
    source.parse_delivery.return_value = push

    return cast(PushSource, source)


def a_source_refusing() -> PushSource:
    """A source that vouches for nothing it is handed."""
    source = create_autospec(PushSource, instance=True)
    source.parse_delivery.side_effect = PushUnverified("dont-care")

    return cast(PushSource, source)


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
        deployed_branch=base_branch,
        github_webhook_secret=secret,
        code_search=code_search
    )
