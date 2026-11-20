"""What is needed to read a repository over GitHub's API.

A module of its own because every request here is sent with it - the headers
are worked out from it, and every read is addressed by it - so it sits beneath
both rather than inside either.
"""

from __future__ import annotations

from core import SettingsSlice


class RepositorySourceSettings(SettingsSlice):
    """What is needed to read a repository, and nothing that could change one.

    The credential here reads source and cannot push. That is the boundary
    rather than a naming preference: it is what lets the source be read from a
    process that must remain incapable of writing anywhere (§13).
    """

    github_api_url: str
    github_repository: str
    github_read_token: str
