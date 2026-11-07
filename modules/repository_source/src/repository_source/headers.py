"""What every request to GitHub's API is sent with.

One place, because five modules here ask GitHub for something, and a header
each of them spells is a rule each of them can get wrong on its own. A
credential is sent only where one is configured: a public repository reads
without one, and "Bearer" with nothing after it is refused before the request
leaves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from repository_source.reading import RepositorySourceSettings

ACCEPT_HEADER: Final = "application/vnd.github+json"


def headers_for(settings: RepositorySourceSettings) -> dict[str, str]:
    """The API's media type, and the read token where one is configured."""
    credential = (
        {"Authorization": f"Bearer {settings.github_read_token}"}
        if settings.github_read_token
        else {}
    )

    return {**credential, "Accept": ACCEPT_HEADER}
