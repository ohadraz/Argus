"""The settings these suites reach a repository under."""

from __future__ import annotations

from code_host.github import GitHubReadSettings, GitHubSettings


def some_settings(api_url: str = "https://api.github.invalid",
                  repository: str = "dont-care/dont-care",
                  read_token: str = "ghp_dont-care-token") -> GitHubReadSettings:
    """One repository and one credential, neither of which reaches GitHub.

    The credential is the reading one: these settings cannot push, which is
    the boundary the read settings exist to hold rather than a naming
    preference.

    The host is deliberately unresolvable: every test here injects its own
    transport, so a request that escaped the double would fail as a connection
    error rather than quietly succeed against something real.
    """
    return GitHubReadSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=read_token
    )


def some_repository_settings(api_url: str = "https://api.github.invalid",
                             repository: str = "dont-care/dont-care",
                             token: str = "ghp_dont-care-token",
                             retries: int = 0,
                             retry_wait_ms: int = 0) -> GitHubSettings:
    """The settings both halves of Code-Fix's act write under - one repository,
    one credential that pushes, and the retry policy.

    No retries unless a test asks for them, so a test about a refusal or an
    unreachable repository makes the one request it is about - and a test that
    asks waits nothing between them.
    """
    return GitHubSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_token=token,
        github_write_retries=retries,
        github_write_retry_wait_ms=retry_wait_ms
    )
