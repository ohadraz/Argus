"""Proposing a code fix as a draft pull request (spec §7.4, §12.1, §13).

The write tier's second action, and the one that stops short on purpose. A pull
request opened here is a *proposal*: it is always a draft, there is no parameter
that makes it anything else, and nothing in this module - or anywhere on this
server - can merge one. Merging is a deploy, and no deploy is among the
mitigations Argus may take unasked (§13), so the enforcement is that the
function does not exist rather than that a check refuses to run.

Opening the pull request is all this does. Putting the patch on the branch it is
opened from is a different job with a different failure, and a module that did
both would report a push that failed and a proposal that was never made with one
exception between them.

The credential is its own, separate from the flag tier's although both are
configured on this process: one can change a flag in the provider and the other
can push code to the target service's repository, and they are scoped to those
two things so that neither becomes the other by being nearby (§14, §15.1).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from argus_core import SettingsSlice
from argus_core.models import OpenedPullRequest

HttpPost = Callable[..., httpx.Response]

REQUEST_TIMEOUT_SECONDS = 10.0

# GitHub's wire vocabulary, named for the fields that carry it rather than for
# the spellings. `DRAFT_FIELD` is the guardrail's own word: the request says
# `draft` and means "not mergeable by one click", and a later reader looking for
# where §13 is enforced finds it by this name.
DRAFT_FIELD = "draft"
HEAD_FIELD = "head"
BASE_FIELD = "base"
TITLE_FIELD = "title"
BODY_FIELD = "body"
NUMBER_FIELD = "number"
READABLE_AT_FIELD = "html_url"

ACCEPT_HEADER = "application/vnd.github+json"


class RepositoryWriteSettings(SettingsSlice):
    """What this tier is allowed to know about the repository it proposes to.

    Deliberately not the flag slice. Both are write-tier credentials and both
    are read by this one process, but a single object naming all of them would
    hand every flag call a token that can push code - and the argument for the
    tier split is exactly that a credential should not be somewhere it has no
    business being.
    """

    github_api_url: str
    github_repository: str
    github_token: str


class PullRequestNotOpened(Exception):
    """No pull request exists, whatever the reason.

    One exception for an unreachable host, a rejected credential, a repository
    that refused the branch and an answer with no pull request in it, because
    the caller's next move is the same for all four: there is nothing to send a
    human to. A proposal reported optimistically would close an incident on a
    link to nothing, which is worse than one that failed loudly - the fix is
    still missing either way, and only one of them says so.
    """


def open_pull_request(head_branch: str,
                      base_branch: str,
                      title: str,
                      body: str,
                      settings: RepositoryWriteSettings,
                      post: HttpPost = httpx.post) -> OpenedPullRequest:
    """Opens a draft pull request from `head_branch` onto `base_branch`.

    `title` and `body` are the agent's own words and are passed through
    unaltered: a human is the entire audience for something nobody may merge,
    and a proposal retitled on the way out is one with its reasoning removed.

    Draft is not a parameter. Every pull request this opens is one, which is
    what keeps the step from proposal to deploy a thing a person does
    deliberately (§13).

    Raises `PullRequestNotOpened` unless the repository accepted the request
    *and* answered with a pull request that can be read back.
    """
    url = f"{settings.github_api_url}/repos/{settings.github_repository}/pulls"

    try:
        response = post(
            url,
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": ACCEPT_HEADER
            },
            json={
                TITLE_FIELD: title,
                BODY_FIELD: body,
                HEAD_FIELD: head_branch,
                BASE_FIELD: base_branch,
                DRAFT_FIELD: True
            },
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise PullRequestNotOpened(
            f"could not open a pull request from [{head_branch}] onto "
            f"[{base_branch}] at [{url}]: {error}"
        ) from error

    return _as_an_opened_pull_request(response, head_branch, url)


def _as_an_opened_pull_request(response: httpx.Response,
                               head_branch: str,
                               url: str) -> OpenedPullRequest:
    """What came back, or the failure that it was not a pull request.

    A 200 carrying nothing usable is the failure that looks most like success -
    a proxy, a rate-limit page, an API that moved - and reading the number as
    absent-but-acceptable would record a proposal with no proposal behind it.
    """
    try:
        answered: dict[str, Any] = response.json()
    except Exception as error:
        raise PullRequestNotOpened(
            f"[{url}] answered {response.status_code} with something that was "
            f"not a pull request: {error}"
        ) from error

    number = answered.get(NUMBER_FIELD)
    readable_at = answered.get(READABLE_AT_FIELD)

    if not isinstance(number, int) or not isinstance(readable_at, str):
        raise PullRequestNotOpened(
            f"[{url}] answered {response.status_code} without a pull request to "
            f"read back: got [{answered}]"
        )

    return OpenedPullRequest(
        number=number, url=readable_at, branch=head_branch
    )
