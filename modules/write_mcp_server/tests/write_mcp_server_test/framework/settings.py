"""The slice the repository-writing tools act under."""

from __future__ import annotations

from write_mcp_server.pull_requests import RepositoryWriteSettings


def some_repository_settings(api_url: str = "https://api.github.invalid",
                             repository: str = "dont-care/dont-care",
                             token: str = "ghp_dont-care-token") -> RepositoryWriteSettings:
    """The same slice the pull request tool writes under - one repository, one
    credential, and both halves of Code-Fix's act reaching it.

    Named for the repository rather than called `some_settings`, because this
    module also has a flag-writing slice and a flag-reading one. Three settings
    builders under one name is three call sites nobody can tell apart.
    """
    return RepositoryWriteSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_token=token
    )
