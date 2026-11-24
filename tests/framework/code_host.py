"""Reading the GitHub double the way the code host would be read.

For the cross-module suites that hand Code-Fix a real write tier but stub its
reads: the one read they cannot stub is where a branch points, since the write
tier writes over the tree of the commit it answers, and a commit the double
does not hold would refuse the write the suite is about.
"""

from __future__ import annotations

from typing import Any, Final

import httpx2
from code_host.github import GitHubReadSettings
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

# GitHub's names for the fields a ref is answered with: the object it points
# at, and that object's sha.
OBJECT_FIELD: Final = "object"
SHA_FIELD: Final = "sha"

_REQUEST_TIMEOUT_SECONDS: Final = 30.0


def the_head_of(branch: str, /) -> str:
    """Where `branch` points in the double's repository, read as the read tier's
    `get_branch_head` reads it."""
    response = httpx2.get(
        f"{GITHUB_DOUBLE_BASE_URL}/repos/{GitHubReadSettings().github_repository}"
        f"/git/ref/heads/{branch}",
        timeout=_REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    found: dict[str, Any] = response.json()

    return str(found[OBJECT_FIELD][SHA_FIELD])
