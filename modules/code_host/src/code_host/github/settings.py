"""What is needed to reach a repository over GitHub's API, in two slices.

Two because the two credentials are not interchangeable. The read token reads
source and cannot push; the write token pushes a branch and opens a pull
request, and can never merge one (§13). A read slice with no field for the
second is what lets the source be read from a process that must remain
incapable of writing anywhere - which is the read tier, and the index - and a
write slice with no field for the first keeps the write tier to the one
credential its writes need.

Slices of the kernel's `Settings` rather than settings of their own: the
repository's name is read outside this adapter too - it is what the index's
record of the repository is kept under, and what a push delivery is checked
against - and two readers of one variable is two chances to disagree about
which repository Argus is in.
"""

from __future__ import annotations

from core import SettingsSlice


class GitHubReadSettings(SettingsSlice):
    """What is needed to read a repository, and nothing that could change one.

    The credential here reads source and cannot push. That is the boundary
    rather than a naming preference: it is what lets the source be read from a
    process that must remain incapable of writing anywhere (§13).
    """

    github_api_url: str
    github_repository: str
    github_read_token: str


class GitHubSettings(SettingsSlice):
    """What the write tier is allowed to know about the repository it proposes
    to: where it is, the credential that pushes to it, and how often a write
    GitHub failed for a moment is made again, and how long before each
    (`retries`).

    No read token: the write tier reads nothing of the repository beyond what
    a write itself asks on the way - where the base points, whether the branch
    or the proposal already landed - and those go under the token that makes
    the write.
    """

    github_api_url: str
    github_repository: str
    github_token: str
    github_write_retries: int
    github_write_retry_wait_ms: int
