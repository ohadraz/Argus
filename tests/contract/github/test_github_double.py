"""Whether the double still compares two commits the way GitHub does.

Every e2e and replay walk reads a deployment's diff from `github_double` and
believes what it says. That belief is checked here the one way it can be: ask
GitHub for a comparison in the Target Service's own repository, ask the double
for one of its own, read both through `the_difference_between` - the reader the
read tier uses - and require the two to read alike.

Alike as that reader reads them, not field by field. The two comparisons are of
different commits and name different files; what every caller depends on is
that each file arrives with a status in GitHub's own vocabulary and with the
change itself, written the way GitHub writes it. A double that sent the name
alone put a `KeyError` where an investigation's evidence should have been, and
no case noticed.

Read-only against a public repository, so this is behind the free contract
session (`nox -s contract`) and needs only a read token.
"""

from __future__ import annotations

from typing import Final
from uuid import uuid4

import httpx2
import pytest
from argus_core import get_settings
from argus_testkit import Assertion, Scenario, all_of
from github_double.repository import DEFAULT_BASE_BRANCH, DEFAULT_FILES
from github_double.server import DEFAULT_BASE_URL
from repository_source import (
    RepositorySourceSettings,
    SourceDifference,
    the_difference_between,
)

# Every status GitHub documents for a file in a comparison (its "diff-entry").
GITHUB_FILE_STATUSES: Final = frozenset({
    "added", "removed", "modified", "renamed", "copied", "changed", "unchanged"
})

# How GitHub begins a patch: at the first hunk, with no file headers above it.
HUNK_HEADER: Final = "@@"

# The head of the real repository's default branch and the commit before it, as
# git spells them - whatever was pushed last is a comparison that changed text.
THE_COMMIT_BEFORE_MAIN: Final = "main~1"
MAIN: Final = "main"

needs_a_real_repository = pytest.mark.skipif(
    not (get_settings().github_read_token and get_settings().github_repository),
    reason="no GITHUB_READ_TOKEN or GITHUB_REPOSITORY: "
           "the real half of the contract cannot be checked"
)


@pytest.mark.contract
@needs_a_real_repository
def test_a_comparison_reads_the_same_from_the_double_as_from_github() -> None:
    # The deployment-diff channel's whole answer. Each file's status is what
    # tells a reader a module arrived rather than changed, and the patch is
    # what tells them code moved rather than configuration - so a double
    # without either has every walk reading evidence GitHub would never send.
    Scenario() \
        .given(at_github := _settings_for(
            get_settings().github_api_url,
            get_settings().github_repository,
            get_settings().github_read_token
        )) \
        .when(lambda: the_difference_between(THE_COMMIT_BEFORE_MAIN, MAIN, at_github)) \
        .then(all_of(_it_names_some_file(), _it_reads_as(_the_double_compared())))


def _the_double_compared() -> SourceDifference:
    """A comparison at the stand-in, of a commit staged for it.

    One fixture file edited and one file added, so the double is asked about
    both kinds of change a deployment makes. Staged rather than found: the
    double starts with one commit, and a comparison needs two.
    """
    httpx2.post(f"{DEFAULT_BASE_URL}/double-control/reset", timeout=10.0).raise_for_status()

    some_path, some_source = next(iter(DEFAULT_FILES.items()))
    some_commit = uuid4().hex
    httpx2.post(
        f"{DEFAULT_BASE_URL}/double-control/stage-commit",
        json={
            "sha": some_commit,
            "files": {
                some_path: f"{some_source}\n# edited by a contract check\n",
                "some_module_a_contract_check_added.py": "print('added')\n"
            }
        },
        timeout=10.0
    ).raise_for_status()

    return the_difference_between(
        DEFAULT_BASE_BRANCH,
        some_commit,
        _settings_for(DEFAULT_BASE_URL, "some-owner/some-repository", "the-double-never-reads-this")
    )


def _it_names_some_file() -> Assertion[SourceDifference]:
    """The comparison GitHub gave changed something.

    Without this the contract holds vacuously: two comparisons naming no file
    read alike whatever either party would have said about one.
    """
    def assertion(from_github: SourceDifference) -> bool:
        if not from_github.files:
            raise AssertionError(
                f"Expected GitHub to name a changed file between [{from_github.base}] "
                f"and [{from_github.head}], it named none."
            )

        return True

    return assertion


def _it_reads_as(at_the_double: SourceDifference) -> Assertion[SourceDifference]:
    """The two comparisons, as the read tier reads them.

    Not file by file: the two name different files of different commits. What
    is compared is what the read tier hands a model for every file - a status
    GitHub would use, and a patch beginning where GitHub begins one.
    """
    def assertion(from_github: SourceDifference) -> bool:
        real, stood_in = _as_read(from_github), _as_read(at_the_double)

        if real != stood_in:
            raise AssertionError(
                f"Expected every file at the double to read as GitHub's do {sorted(real)}, "
                f"they read {sorted(stood_in)}: "
                f"{[(each.path, each.status, each.patch) for each in at_the_double.files]}."
            )

        return True

    return assertion


def _as_read(difference: SourceDifference) -> set[tuple[str, str]]:
    """Each file's status and patch, as whether GitHub would have said them so."""
    return {
        (
            "a status GitHub uses" if changed.status in GITHUB_FILE_STATUSES
            else f"a status GitHub never uses [{changed.status}]",
            "a patch from the first hunk" if (changed.patch or "").startswith(HUNK_HEADER)
            else "no patch GitHub would send"
        )
        for changed in difference.files
    }


def _settings_for(api_url: str, repository: str, token: str) -> RepositorySourceSettings:
    return RepositorySourceSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=token
    )
