"""What every request to GitHub's API is sent with.

One place, because every module here asks GitHub for something and each had its
own copy - so a credential left unset broke all of them the same way, and a fix
made in one would have left the rest.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_testkit import Assertion, Scenario, all_of
from code_host.github.headers import (
    ACCEPT_HEADER,
    AUTHORIZATION_HEADER,
    BEARER_SCHEME,
    GITHUB_MEDIA_TYPE,
    headers_for,
    write_headers_for,
)

from code_host_test.framework.settings import some_repository_settings, some_settings


@pytest.mark.unit
def test_a_request_bears_the_read_token_it_is_given() -> None:
    some_read_token = "ghp_some-read-only-token"

    Scenario() \
        .when(lambda: headers_for(some_settings(read_token=some_read_token))) \
        .then(all_of(_it_authorizes_with(f"{BEARER_SCHEME} {some_read_token}")))


@pytest.mark.unit
def test_a_request_with_no_read_token_configured_bears_no_credential() -> None:
    # A public repository reads without one. "Bearer" with nothing after it is
    # refused before the request leaves, so every read failed wherever the
    # token was left unset - CI's included.
    Scenario() \
        .when(lambda: headers_for(some_settings(read_token=""))) \
        .then(all_of(_it_authorizes_with(None)))


@pytest.mark.unit
def test_a_write_bears_the_token_that_pushes() -> None:
    some_token = "ghp_some-token-that-pushes"

    Scenario() \
        .when(lambda: write_headers_for(some_repository_settings(token=some_token))) \
        .then(all_of(_it_authorizes_with(f"{BEARER_SCHEME} {some_token}")))


@pytest.mark.unit
def test_a_write_with_no_token_configured_bears_no_credential() -> None:
    # GitHub refuses the write in its own words, which name the missing
    # credential; "Bearer" with nothing after it is refused before the request
    # leaves, in words that name none.
    Scenario() \
        .when(lambda: write_headers_for(some_repository_settings(token=""))) \
        .then(all_of(_it_authorizes_with(None)))


@pytest.mark.unit
@pytest.mark.parametrize("headers", [
    pytest.param(lambda: headers_for(some_settings()), id="a-read"),
    pytest.param(lambda: write_headers_for(some_repository_settings()), id="a-write")
])
def test_a_request_asks_for_the_api_s_own_media_type(
    headers: Callable[[], dict[str, str]]
) -> None:
    # The REST API's documented media type. Without it GitHub answers in its
    # default, which it is free to change under every reader here.
    Scenario() \
        .when(headers) \
        .then(_it_accepts(GITHUB_MEDIA_TYPE))


def _it_authorizes_with(expected: str | None) -> Assertion[dict[str, str]]:
    def assertion(headers: dict[str, str]) -> bool:
        if headers.get(AUTHORIZATION_HEADER) != expected:
            raise AssertionError(
                f"Expected the request to authorize with [{expected}], it bore "
                f"[{headers.get(AUTHORIZATION_HEADER)}]."
            )

        return True

    return assertion


def _it_accepts(expected: str) -> Assertion[dict[str, str]]:
    def assertion(headers: dict[str, str]) -> bool:
        if headers.get(ACCEPT_HEADER) != expected:
            raise AssertionError(
                f"Expected the request to accept [{expected}], it asked for "
                f"[{headers.get(ACCEPT_HEADER)}]."
            )

        return True

    return assertion
