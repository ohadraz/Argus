"""What every request to GitHub's API is sent with.

One place, because five modules here ask GitHub for something and each had its
own copy - so a credential left unset broke all five the same way, and a fix
made in one would have left four.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of
from repository_source import RepositorySourceSettings
from repository_source.headers import headers_for

AUTHORIZATION = "Authorization"


@pytest.mark.unit
def test_a_request_bears_the_read_token_it_is_given() -> None:
    some_read_token = "ghp_some-read-only-token"

    Scenario() \
        .when(lambda: headers_for(_some_settings(read_token=some_read_token))) \
        .then(all_of(_it_authorizes_with(f"Bearer {some_read_token}")))


@pytest.mark.unit
def test_a_request_with_no_read_token_configured_bears_no_credential() -> None:
    # A public repository reads without one. "Bearer" with nothing after it is
    # refused before the request leaves, so every read failed wherever the
    # token was left unset - CI's included.
    Scenario() \
        .when(lambda: headers_for(_some_settings(read_token=""))) \
        .then(all_of(_it_authorizes_with(None)))


def _some_settings(read_token: str) -> RepositorySourceSettings:
    return RepositorySourceSettings(
        github_api_url="https://api.github.invalid",
        github_repository="dont-care/dont-care",
        github_read_token=read_token
    )


def _it_authorizes_with(expected: str | None) -> Assertion[dict[str, str]]:
    def assertion(headers: dict[str, str]) -> bool:
        if headers.get(AUTHORIZATION) != expected:
            raise AssertionError(
                f"Expected the request to authorize with [{expected}], it bore "
                f"[{headers.get(AUTHORIZATION)}]."
            )

        return True

    return assertion
