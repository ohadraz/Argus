"""Opening the draft pull request a code fix is proposed as (spec §7.4, §13).

The one tool in this tier whose guardrail is what it *cannot* do. A pull request
Argus opened is a proposal; a pull request merged is a deploy, and that is the
line the autonomy tiers are drawn at - so the thing asserted hardest here is
that what gets opened is a draft, every time and with no parameter that could
make it anything else.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from write_mcp_server.pull_requests import (
    PullRequestNotOpened,
    open_pull_request,
)

from write_mcp_server_test.framework.settings import some_repository_settings

DONT_CARE_BRANCH = "dont-care-branch"
DONT_CARE_BASE = "main"
DONT_CARE_TITLE = "dont care title"
DONT_CARE_BODY = "dont care body"


@pytest.mark.unit
def test_a_fix_is_proposed_from_its_own_branch_against_the_one_it_fixes() -> None:
    some_branch = "argus/fix-monthly-spend-divisor"
    some_base = "main"
    repository = a_repository_that_opens_pull_requests()

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=some_branch,
                base_branch=some_base,
                title=DONT_CARE_TITLE,
                body=DONT_CARE_BODY,
                settings=some_repository_settings(),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_request_asked_to_merge(repository, some_branch, into=some_base)
            )
        )


@pytest.mark.unit
def test_a_proposed_fix_is_opened_as_a_draft() -> None:
    # The guardrail, and the reason this module exists rather than a general
    # "call GitHub" tool: a draft cannot be merged by clicking once, so the step
    # from proposal to deploy stays a thing a human does deliberately (§13).
    # There is no parameter for this - it is not the caller's to decide.
    repository = a_repository_that_opens_pull_requests()

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                title=DONT_CARE_TITLE,
                body=DONT_CARE_BODY,
                settings=some_repository_settings(),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_request_body_said(repository, "draft", True)
            )
        )


@pytest.mark.unit
def test_a_proposed_fix_carries_the_words_it_was_given() -> None:
    # A human is the whole audience for a draft nobody may merge. A PR that
    # arrived titled by this module rather than by the agent that reasoned about
    # the fault would be a proposal with its reasoning stripped off.
    some_title = "fix: the monthly figure divides by an empty month"
    some_body = "Traced from incident 41: `total_this_month_cents // 0`."
    repository = a_repository_that_opens_pull_requests()

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                title=some_title,
                body=some_body,
                settings=some_repository_settings(),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_request_body_said(repository, "title", some_title),
                _the_request_body_said(repository, "body", some_body)
            )
        )


@pytest.mark.unit
def test_a_proposed_fix_addresses_the_repository_it_is_proposed_to() -> None:
    some_repository = "io-shop/argus-target-service"
    some_api_url = "https://api.github.invalid"
    repository = a_repository_that_opens_pull_requests()

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                title=DONT_CARE_TITLE,
                body=DONT_CARE_BODY,
                settings=some_repository_settings(
                    api_url=some_api_url, repository=some_repository
                ),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_request_went_to(
                    repository, f"{some_api_url}/repos/{some_repository}/pulls"
                )
            )
        )


@pytest.mark.unit
def test_a_proposed_fix_is_written_under_the_credential_that_can_write() -> None:
    # Scoped to the target service's repository alone (§15.1): Argus proposes
    # changes to the shop, never to itself. A credential that could reach this
    # repo would make that a matter of what the agent chose to type.
    some_token = "ghp_some-repository-token"
    repository = a_repository_that_opens_pull_requests()

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                title=DONT_CARE_TITLE,
                body=DONT_CARE_BODY,
                settings=some_repository_settings(token=some_token),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_request_was_authorized_with(repository, f"Bearer {some_token}")
            )
        )


@pytest.mark.unit
def test_an_opened_pull_request_carries_where_a_human_can_read_it() -> None:
    # The number and the link are the whole point of the return value: this is
    # the one action in the walk that finishes with somebody else's turn, and an
    # agent that could not say where to go would have proposed nothing anyone
    # could find.
    some_number = 41
    some_url = "https://github.invalid/io-shop/argus-target-service/pull/41"
    repository = a_repository_that_opens_pull_requests(
        number=some_number, url=some_url
    )

    Scenario() \
        .when(
            lambda: open_pull_request(
                head_branch=DONT_CARE_BRANCH,
                base_branch=DONT_CARE_BASE,
                title=DONT_CARE_TITLE,
                body=DONT_CARE_BODY,
                settings=some_repository_settings(),
                post=repository.post
            )
        ) \
        .then(
            all_of(
                _the_pull_request_is_numbered(some_number),
                _the_pull_request_is_readable_at(some_url)
            )
        )


@pytest.mark.unit
def test_a_repository_that_refuses_is_not_reported_as_a_pull_request_opened() -> None:
    # Same reason a flag that never landed raises: the caller's next move is to
    # tell a human where to look, and a fix reported as proposed but never
    # opened is an incident closed on a link to nothing.
    repository = a_repository_that_opens_pull_requests()
    repository.post.return_value = httpx.Response(
        status_code=422,
        json={"message": "No commits between main and argus/fix"},
        request=httpx.Request("POST", "http://github.invalid/")
    )

    Scenario() \
        .when(attempting(lambda: _opening_against(repository))) \
        .then(
            all_of(
                an_error_was_raised(PullRequestNotOpened)
            )
        )


@pytest.mark.unit
def test_an_unreachable_repository_is_not_reported_as_a_pull_request_opened() -> None:
    some_transport_error = httpx.ConnectError("connection refused")
    repository = a_repository_that_opens_pull_requests()
    repository.post.side_effect = some_transport_error

    Scenario() \
        .when(attempting(lambda: _opening_against(repository))) \
        .then(
            all_of(
                an_error_was_raised(PullRequestNotOpened)
            )
        )


@pytest.mark.unit
def test_a_repository_answering_without_a_pull_request_is_not_reported_as_one() -> None:
    # A 200 carrying nothing usable is the failure that looks like success. It
    # is what a proxy, a rate-limit page or a changed API returns, and taking
    # the number as absent-but-fine would record a proposal with no proposal
    # behind it.
    repository = a_repository_that_opens_pull_requests()
    repository.post.return_value = httpx.Response(
        status_code=200,
        json={},
        request=httpx.Request("POST", "http://github.invalid/")
    )

    Scenario() \
        .when(attempting(lambda: _opening_against(repository))) \
        .then(
            all_of(
                an_error_was_raised(PullRequestNotOpened)
            )
        )


def _the_request_asked_to_merge(repository: _Repository,
                                branch: str,
                                *,
                                into: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        body = _request_body(repository)

        if body.get("head") != branch:
            raise AssertionError(
                f"Expected the pull request to come from [{branch}], "
                f"got [{body.get('head')}]."
            )

        if body.get("base") != into:
            raise AssertionError(
                f"Expected the pull request to target [{into}], "
                f"got [{body.get('base')}]."
            )

        return True

    return assertion


def _the_request_body_said(repository: _Repository,
                           field: str,
                           expected: Any) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = _request_body(repository).get(field)

        if said != expected:
            raise AssertionError(
                f"Expected the request's [{field}] to be [{expected!r}], "
                f"got [{said!r}]."
            )

        return True

    return assertion


def _the_request_went_to(repository: _Repository, url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = repository.post.call_args.args[0]

        if addressed != url:
            raise AssertionError(f"Expected a request to [{url}], got [{addressed}].")

        return True

    return assertion


def _the_request_was_authorized_with(repository: _Repository,
                                     credential: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        sent = repository.post.call_args.kwargs["headers"].get("Authorization")

        if sent != credential:
            raise AssertionError(
                f"Expected the request to authorize with [{credential}], got [{sent}]."
            )

        return True

    return assertion


def _the_pull_request_is_numbered(number: int) -> Assertion[Any]:
    def assertion(opened: Any) -> bool:
        if opened.number != number:
            raise AssertionError(
                f"Expected pull request #{number}, got #{opened.number}."
            )

        return True

    return assertion


def _the_pull_request_is_readable_at(url: str) -> Assertion[Any]:
    def assertion(opened: Any) -> bool:
        if opened.url != url:
            raise AssertionError(
                f"Expected the pull request to be readable at [{url}], "
                f"got [{opened.url}]."
            )

        return True

    return assertion


def _request_body(repository: _Repository) -> dict[str, Any]:
    body: dict[str, Any] = repository.post.call_args.kwargs["json"]

    return body


def _opening_against(repository: _Repository) -> Any:
    """One call, for the tests that are about how it fails rather than what it
    sent - so a failure case reads as the thing it is asserting and not as a
    fifth repetition of the arguments."""
    return open_pull_request(
        head_branch=DONT_CARE_BRANCH,
        base_branch=DONT_CARE_BASE,
        title=DONT_CARE_TITLE,
        body=DONT_CARE_BODY,
        settings=some_repository_settings(),
        post=repository.post
    )


class _Repository:
    def __init__(self) -> None:
        self.post: Any = create_autospec(httpx.post)


def a_repository_that_opens_pull_requests(
        number: int = 1,
        url: str = "https://github.invalid/dont-care/dont-care/pull/1"
) -> _Repository:
    repository = _Repository()
    repository.post.return_value = httpx.Response(
        status_code=201,
        json={"number": number, "html_url": url},
        request=httpx.Request("POST", "http://github.invalid/")
    )

    return repository
