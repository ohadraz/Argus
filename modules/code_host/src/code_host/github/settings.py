"""What is needed to reach a repository over GitHub's API, in two settings.

Two because the two credentials are not interchangeable. The read token reads
source and cannot push; the write token pushes a branch and opens a pull
request, and can never merge one (§13). Read settings with no field for the
second is what lets the source be read from a process that must remain
incapable of writing anywhere - which is the read tier, and the index - and
write settings with no field for the first keep the write tier to the one
credential its writes need.

Both read the repository from the one variable, `GITHUB_REPOSITORY`, declared
once, on the base they share. The push source's settings (`push_source.github`)
read the same variable and declare it again, since that adapter knows only the
kernel: the repository's name is also what the index's record is kept under and
what a push delivery is checked against. Each defaults to empty, which names no
repository - so a deployment names one repository for all of them, or none.
"""

from __future__ import annotations

from typing import Final, Self

from core import AdapterSettings
from pydantic import Field, model_validator

# The environment variable the service's source paths were once read from, and
# the one it became. Refused where set, never read: a setting nobody declares is
# ignored, so a deployment still using the old name would run on the default
# and nothing would say so. GitHub's to refuse because the old name is spelled
# in GitHub's namespace - and every process that reads the new one reads a
# repository through this adapter.
RETIRED_SOURCE_PATHS: Final = "GITHUB_SOURCE_PATHS"
SOURCE_PATHS: Final = "SERVICE_SOURCE_PATHS"


class GitHubRepositorySettings(AdapterSettings):
    """Which repository, and where GitHub's API answers for it.

    The Target Service's repository is the only repository Argus may propose a
    change to (spec §15.1). Named in full - `owner/name` - because that is how
    the API addresses one, and because a deployment that had to assemble it from
    two settings could assemble a different one.
    """

    github_api_url: str = Field(default="https://api.github.com")
    github_repository: str = Field(default="")
    # The name the service's source paths went by before they said whose paths
    # they are. Read only to be refused (`_no_retired_names`): a deployment still
    # spelling it this way would start on the whole repository and change what
    # Code-Fix reads with no word why.
    retired_source_paths: str | None = Field(default=None,
                                             validation_alias=RETIRED_SOURCE_PATHS,
                                             exclude=True)

    @model_validator(mode="after")
    def _no_retired_names(self) -> Self:
        """Refuses to start on a setting spelled by a name it no longer has.

        Set at all, empty included: the old name says the deployment meant to
        configure this, and whatever it holds is not what is read.
        """
        if self.retired_source_paths is not None:
            raise ValueError(
                f"{RETIRED_SOURCE_PATHS} is set and is no longer read: the directories "
                f"of the repository that hold the service are {SOURCE_PATHS} now. "
                f"Rename it, or Argus reads the whole repository"
            )

        return self


class GitHubReadSettings(GitHubRepositorySettings):
    """What is needed to read a repository, and nothing that could change one.

    The credential here reads source and cannot push. That is the boundary
    rather than a naming preference: it is what lets the source be read from a
    process that must remain incapable of writing anywhere (§13) - the same
    argument that keeps the flag evaluation token there and the admin token out.
    """

    github_read_token: str = Field(default="")


class GitHubSettings(GitHubRepositorySettings):
    """What the write tier is allowed to know about the repository it proposes
    to: where it is, the credential that pushes to it, and how often a write
    GitHub failed for a moment is made again, and how long before each.

    No read token: the write tier reads nothing of the repository beyond what
    a write itself asks on the way - the tree of the commit it writes on,
    whether the branch or the proposal already landed - and those go under the
    token that makes the write.
    """

    # Scoped to the repository above and to nothing else: "Argus cannot touch
    # its own codebase" is a property of what this token reaches, not of what
    # the agent was told (§15.1). Empty by default for the same reason the admin
    # token is - a misconfigured write server should fail loudly rather than
    # quietly authenticate as nobody. It can never merge what it opens (§13).
    github_token: str = Field(default="")
    # Retries, tries after the first: two is three in all. Made again only where
    # GitHub failed the write for a moment - never reached, or answered with a
    # 5xx; a refusal, a 4xx, is never made again.
    github_write_retries: int = Field(default=2, ge=0)
    github_write_retry_wait_ms: int = Field(default=200, ge=0)
