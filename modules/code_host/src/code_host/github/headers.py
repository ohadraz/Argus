"""What every request to GitHub's API is sent with.

One place, because every module here asks GitHub for something, and a header
each of them spells is a rule each of them can get wrong on its own. A
credential is sent only where one is configured: a public repository reads
without one, and "Bearer" with nothing after it is refused before the request
leaves - in words that name no credential, where GitHub refuses a write without
one in its own.
"""

from __future__ import annotations

from typing import Final

from code_host.github.settings import GitHubReadSettings, GitHubSettings

# The two headers every request carries, and what goes in each: the media type
# GitHub's REST API answers in, and a token under the scheme GitHub reads.
ACCEPT_HEADER: Final = "Accept"
GITHUB_MEDIA_TYPE: Final = "application/vnd.github+json"
AUTHORIZATION_HEADER: Final = "Authorization"
BEARER_SCHEME: Final = "Bearer"


def headers_for(settings: GitHubReadSettings) -> dict[str, str]:
    """The API's media type, and the read token where one is configured."""
    return _with(settings.github_read_token)


def write_headers_for(settings: GitHubSettings) -> dict[str, str]:
    """The API's media type, and the write token where one is configured."""
    return _with(settings.github_token)


def _with(token: str) -> dict[str, str]:
    credential = {AUTHORIZATION_HEADER: f"{BEARER_SCHEME} {token}"} if token else {}

    return {**credential, ACCEPT_HEADER: GITHUB_MEDIA_TYPE}
