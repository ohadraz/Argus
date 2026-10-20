"""Whether a branch holds a commit - whether the commit is in its history.

What Code-Fix is told before it reads anything. It reads one branch, and the
revision running when the alert fired may never have been merged into it -
deployed from a branch of its own, so the files read are not the files that
ran. Asked rather than assumed either way: a caveat said on every incident is
one said on the ordinary case, where the branch holds what ran.

GitHub answers it as part of a comparison, from where the second commit stands
to the first. Beside `comparing.py` rather than inside it, because that one
answers what changed and this one answers how two commits stand, and neither
reads the other's half of the answer.
"""

from __future__ import annotations

from typing import Any, Final

import httpx2

from repository_source.comparing import BETWEEN
from repository_source.reading import (
    ACCEPT_HEADER,
    HttpGet,
    RepositorySourceSettings,
    RepositoryUnreadable,
)

# GitHub's word for how the head of a comparison stands to its base, and the
# two of its four that put the base in the head's history: the head has moved
# past it, or is it. `behind` and `diverged` are the other two.
STATUS_FIELD: Final = "status"
AHEAD_STATUS: Final = "ahead"
IDENTICAL_STATUS: Final = "identical"

HOLDING_TIMEOUT_SECONDS: Final = 10.0


def the_branch_holds(branch: str,
                     revision: str,
                     settings: RepositorySourceSettings,
                     get: HttpGet = httpx2.get) -> bool:
    """Whether `revision` is in `branch`'s history.

    Compared from the revision to the branch, and the order is the answer:
    reversed, `ahead` would say the revision had moved past the branch.

    Raises `RepositoryUnreadable` rather than answering `False`. Told that what
    ran is not on the branch, Code-Fix hedges every claim it makes about the
    code, and a repository nobody could reach established no such thing.
    """
    url = (
        f"{settings.github_api_url}/repos/{settings.github_repository}"
        f"/compare/{revision}{BETWEEN}{branch}"
    )

    try:
        response = get(url, headers=_headers(settings), timeout=HOLDING_TIMEOUT_SECONDS)
        response.raise_for_status()
        compared: dict[str, Any] = response.json()
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not tell whether [{branch}] holds [{revision}] in "
            f"[{settings.github_repository}]: {error}"
        ) from error

    return compared.get(STATUS_FIELD) in (AHEAD_STATUS, IDENTICAL_STATUS)


def _headers(settings: RepositorySourceSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_read_token}",
        "Accept": ACCEPT_HEADER
    }
