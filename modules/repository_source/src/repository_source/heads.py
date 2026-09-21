"""Where a branch currently points (spec §11).

What a catch-up pass asks when nothing has told it anything. A push webhook
records where the repository went, but a deployment that has never received a
delivery - no tunnel, a webhook nobody configured, a secret that does not
match - has no record at all, and an index that waited to be told would then
never be built.

That is the difference between a reconciler and an edge-triggered handler
wearing the name: desired state is a fact about the repository, and where it
cannot be remembered it can be asked for.

One call, one string. Deliberately not a way to read anything - the answer is
a commit id, and everything that reads code at a commit is elsewhere here.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from repository_source.reading import (
    ACCEPT_HEADER,
    HttpGet,
    RepositorySourceSettings,
    RepositoryUnreadable,
)

SHA_FIELD: Final = "sha"

# How a branch is named to an endpoint that also takes tags and commit ids. A
# bare name would leave the API to choose, and a repository holding a `main`
# tag from some release would have the index built at whatever that tag froze
# rather than at what is deployed.
BRANCH_REF_PREFIX: Final = "heads/"

HEAD_TIMEOUT_SECONDS: Final = 10.0


def the_head_of(branch: str,
                settings: RepositorySourceSettings,
                get: HttpGet = httpx.get) -> str:
    """The commit `branch` points at.

    Raises `RepositoryUnreadable` rather than answering emptily. Nothing
    sensible is available instead: an empty string compared against the
    indexed commit would differ from it, and a catch-up pass would then try to
    build an index at a commit that does not exist, every pass, forever.
    """
    url = (
        f"{settings.github_api_url}/repos/{settings.github_repository}"
        f"/commits/{BRANCH_REF_PREFIX}{branch}"
    )

    try:
        response = get(
            url, headers=_headers(settings), timeout=HEAD_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        answered: dict[str, Any] = response.json()

        return str(answered[SHA_FIELD])
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not read where [{branch}] points in "
            f"[{settings.github_repository}]: {error}"
        ) from error


def _headers(settings: RepositorySourceSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_read_token}",
        "Accept": ACCEPT_HEADER
    }
