"""Where a deployed revision can be read, as a person opens it.

A deployment platform names the repository it synced from by the address it
clones, which is not the address a reader opens. On GitHub the two are close:
the clone address over HTTPS, less its `.git` - and the commit and the
directory at that commit are pages under it. A host whose pages this does not
know gets no addresses at all, rather than ones that lead nowhere.

The repository is named by owner and name on any host, since that is what tells
two repositories apart and takes no knowledge of the host's pages.
"""

from __future__ import annotations

import pytest
from argus_core.models import RevisionSource
from argus_testkit import Scenario, the_answer_was
from repository_source import owner_and_name, where_to_read

SOME_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"

# The repository as a reader opens it.
THE_REPOSITORY = "https://github.com/ohadraz/Argus-Demo-Target-App"


@pytest.mark.unit
@pytest.mark.parametrize("cloned_from", [
    "https://github.com/ohadraz/Argus-Demo-Target-App",
    "https://github.com/ohadraz/Argus-Demo-Target-App.git",
    "https://github.com/ohadraz/Argus-Demo-Target-App.git/",
    "git@github.com:ohadraz/Argus-Demo-Target-App.git",
    "https://GitHub.com/ohadraz/Argus-Demo-Target-App"
], ids=["https", "a url ending in .git", "a url ending in .git and a slash", "ssh",
        "a host in capitals"])
def test_a_revision_on_github_is_opened_at_its_commit_and_its_directory(cloned_from: str) -> None:
    Scenario() \
        .when(
            lambda: where_to_read(cloned_from, SOME_REVISION, "deploy")
        ) \
        .then(
            the_answer_was(RevisionSource(
                repository="ohadraz/Argus-Demo-Target-App",
                repository_address=THE_REPOSITORY,
                revision_address=f"{THE_REPOSITORY}/commit/{SOME_REVISION}",
                directory="deploy",
                directory_address=f"{THE_REPOSITORY}/tree/{SOME_REVISION}/deploy"))
        )


@pytest.mark.unit
def test_a_directory_is_opened_by_its_path_without_the_slashes_around_it() -> None:
    Scenario() \
        .when(
            lambda: where_to_read(THE_REPOSITORY, SOME_REVISION, "/apps/shop/")
        ) \
        .then(
            the_answer_was(RevisionSource(
                repository="ohadraz/Argus-Demo-Target-App",
                repository_address=THE_REPOSITORY,
                revision_address=f"{THE_REPOSITORY}/commit/{SOME_REVISION}",
                directory="apps/shop",
                directory_address=f"{THE_REPOSITORY}/tree/{SOME_REVISION}/apps/shop"))
        )


@pytest.mark.unit
@pytest.mark.parametrize("synced_from", [None, "", "/"],
                         ids=["not said", "empty", "a bare slash"])
def test_a_revision_synced_from_the_root_or_from_nowhere_said_has_no_directory_to_open(
    synced_from: str | None
) -> None:
    # The root is the repository itself, which has its own link; and where the
    # platform said nothing there is no directory to name.
    Scenario() \
        .when(
            lambda: where_to_read(THE_REPOSITORY, SOME_REVISION, synced_from)
        ) \
        .then(
            the_answer_was(RevisionSource(
                repository="ohadraz/Argus-Demo-Target-App",
                repository_address=THE_REPOSITORY,
                revision_address=f"{THE_REPOSITORY}/commit/{SOME_REVISION}"))
        )


@pytest.mark.unit
def test_a_repository_on_a_host_whose_pages_are_unknown_has_nothing_to_open() -> None:
    Scenario() \
        .when(
            lambda: where_to_read("https://gitlab.example.com/team/shop.git", SOME_REVISION,
                                  "deploy")
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
@pytest.mark.parametrize("cloned_from", [
    "https://github.com/kuki/k8s-configs",
    "https://github.com/kuki/k8s-configs.git/",
    "git@github.com:kuki/k8s-configs.git",
    "https://gitlab.example.com/kuki/k8s-configs.git"
], ids=["https", "a url ending in .git and a slash", "ssh", "another host"])
def test_a_repository_is_named_by_its_owner_and_name_on_any_host(cloned_from: str) -> None:
    Scenario() \
        .when(
            lambda: owner_and_name(cloned_from)
        ) \
        .then(
            the_answer_was("kuki/k8s-configs")
        )
