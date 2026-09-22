"""The slice these suites read a repository under."""

from __future__ import annotations

from repository_source import RepositorySourceSettings


def some_settings(api_url: str = "https://api.github.invalid",
                  repository: str = "dont-care/dont-care",
                  read_token: str = "ghp_dont-care-token") -> RepositorySourceSettings:
    """One repository and one credential, neither of which reaches GitHub.

    The credential is the reading one: this slice cannot push, which is the
    boundary the module exists to hold rather than a naming preference.

    The host is deliberately unresolvable: every test here injects its own
    transport, so a request that escaped the double would fail as a connection
    error rather than quietly succeed against something real.
    """
    return RepositorySourceSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=read_token
    )
