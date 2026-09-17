"""Bringing the index up to what is deployed (spec §11).

One pass: what commit the passages describe, what commit the repository is at,
and the work between them. Nothing here counts attempts or records that work
is owed - a pass that failed leaves the two commits differing, so the next one
finds the same work waiting. That difference *is* the retry, and it is why
there is no queue to drain and no backoff to tune.

Backfill and incremental are one code path. An index that has never been built
has nothing to compare against, so everything is considered; one that has
fallen behind considers what changed. Neither is a branch on "is this the
first time" - it is the same call with a different list of paths, and `None`
means "all of them".

The pass never waits to be told. A deployment that has received no push
delivery - no tunnel, a webhook nobody set up, a secret that does not match -
has nothing recorded, and asking the repository where its branch is, is what
makes this level-triggered rather than an edge-triggered handler wearing a
reconciler's name.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from code_index.building import IndexSettings
from code_index.reconciling import (
    BranchHead,
    ChangedPaths,
    Indexer,
    IndexRecord,
    reconcile,
)
from code_index.records import RepositoryIndex
from repository_source import RepositoryUnreadable

THE_REPOSITORY = "ohadraz/Argus-Demo-Target-App"
THE_DEPLOYED_BRANCH = "main"

WHAT_IS_INDEXED = "3f1b9d2c8a7e6f5d4c3b2a1908f7e6d5c4b3a291"
WHAT_IS_DEPLOYED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

SOME_FILE_THAT_CHANGED = "src/io_shop/spend_summary.py"

# This suite never cuts a file - the indexer is a double - so the bounds only
# have to be a pair a `Settings` would accept.
DONT_CARE_MAX_LINES = 60
DONT_CARE_OVERLAP = 10


@pytest.mark.unit
def test_an_index_that_has_never_been_built_is_built_whole() -> None:
    # The backfill, and not a special case: nothing is recorded, so nothing can
    # be compared against, so everything is considered. The store holds none of
    # it, which is what makes "consider everything" cheap to say and expensive
    # only the once.
    index = an_indexer()

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=nothing_recorded(),
                head_of=a_branch_at(WHAT_IS_DEPLOYED),
                changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                index=index
            )
        ) \
        .then(
            all_of(
                _the_index_was_brought_to(index, WHAT_IS_DEPLOYED),
                _the_whole_repository_was_considered(index),
                _what_came_back_is(WHAT_IS_DEPLOYED)
            )
        )


@pytest.mark.unit
def test_an_index_that_has_fallen_behind_considers_only_what_changed() -> None:
    # The reason the comparison exists. Everything unchanged is already held
    # under an id derived from what it says, so a full pass embeds nothing it
    # has seen - but it asks the store once per file to find that out, and at a
    # hundred thousand files that is the whole cost of the pass.
    index = an_indexer()

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=an_index_at(WHAT_IS_INDEXED, pushed=WHAT_IS_DEPLOYED),
                head_of=a_branch_at(WHAT_IS_DEPLOYED),
                changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                index=index
            )
        ) \
        .then(
            all_of(
                _the_index_was_brought_to(index, WHAT_IS_DEPLOYED),
                _the_paths_considered_were(index, [SOME_FILE_THAT_CHANGED])
            )
        )


@pytest.mark.unit
def test_an_index_already_describing_what_is_deployed_is_left_alone() -> None:
    # The ordinary pass, and the common one: a loop that woke up, found the two
    # commits equal and went back to sleep without reading a repository or
    # touching a store.
    index = an_indexer()

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=an_index_at(WHAT_IS_DEPLOYED, pushed=WHAT_IS_DEPLOYED),
                head_of=a_branch_at(WHAT_IS_DEPLOYED),
                changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                index=index
            )
        ) \
        .then(
            all_of(
                _nothing_was_indexed(index),
                _what_came_back_is(None)
            )
        )


@pytest.mark.unit
def test_a_repository_nothing_has_reported_a_push_for_is_asked_where_it_is() -> None:
    # THE ONE THAT MATTERS WITHOUT A WEBHOOK. A delivery that never arrives -
    # no tunnel, a secret that does not match - leaves `pending_sha` empty
    # forever, and an index that waited to be told would never be built at all.
    # Asking turns a missed notification into a delay.
    branch = a_branch_at(WHAT_IS_DEPLOYED)
    index = an_indexer()

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=an_index_at(WHAT_IS_INDEXED, pushed=None),
                head_of=branch,
                changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                index=index
            )
        ) \
        .then(
            all_of(
                _the_branch_asked_about_was(branch, THE_DEPLOYED_BRANCH),
                _the_index_was_brought_to(index, WHAT_IS_DEPLOYED)
            )
        )


@pytest.mark.unit
def test_a_push_that_was_reported_is_not_asked_about_again() -> None:
    # The webhook's whole contribution: knowing without asking. A pass that
    # called the provider anyway would make the notification decorative and
    # spend an API call every cycle to learn what it had been handed.
    branch = a_branch_at(WHAT_IS_DEPLOYED)

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=an_index_at(WHAT_IS_INDEXED, pushed=WHAT_IS_DEPLOYED),
                head_of=branch,
                changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                index=an_indexer()
            )
        ) \
        .then(_the_branch_was_not_asked_about(branch))


@pytest.mark.unit
def test_a_comparison_that_cannot_say_has_the_whole_repository_considered() -> None:
    # GitHub lists at most three hundred changed files and does not say when it
    # stopped. Trusted, a rebase or a formatting sweep would leave most of the
    # repository unindexed under a watermark claiming it was current - so an
    # answer that cannot be trusted is treated as no answer.
    index = an_indexer()

    Scenario() \
        .when(
            lambda: reconcile(
                settings=some_settings(),
                recorded=an_index_at(WHAT_IS_INDEXED, pushed=WHAT_IS_DEPLOYED),
                head_of=a_branch_at(WHAT_IS_DEPLOYED),
                changed_between=a_comparison_that_cannot_say(),
                index=index
            )
        ) \
        .then(_the_whole_repository_was_considered(index))


@pytest.mark.unit
def test_a_pass_that_failed_leaves_the_work_where_it_was() -> None:
    # No attempt counter, no backoff, nothing recorded. The difference between
    # the two commits is still there when the next pass looks, which is the
    # whole retry mechanism - and swallowing the failure here would be the one
    # way to lose it.
    index = an_indexer()
    index.side_effect = RepositoryUnreadable("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: reconcile(
                    settings=some_settings(),
                    recorded=an_index_at(WHAT_IS_INDEXED, pushed=WHAT_IS_DEPLOYED),
                    head_of=a_branch_at(WHAT_IS_DEPLOYED),
                    changed_between=a_comparison_naming(SOME_FILE_THAT_CHANGED),
                    index=index
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


def _the_index_was_brought_to(index: Any, sha: str) -> Assertion[Any]:
    """Which commit the passages are being made to describe."""
    def assertion(dont_care_result: Any) -> bool:
        asked = index.call_args

        if asked is None or asked.args[0:1] != (sha,):
            raise AssertionError(f"Expected the index brought to [{sha}], got [{asked}].")

        return True

    return assertion


def _the_paths_considered_were(index: Any, paths: list[str]) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        considered = index.call_args.args[1]

        if considered != paths:
            raise AssertionError(f"Expected the paths {paths}, got {considered}.")

        return True

    return assertion


def _the_whole_repository_was_considered(index: Any) -> Assertion[Any]:
    """No list of paths at all, which is how "all of them" is said."""
    def assertion(dont_care_result: Any) -> bool:
        considered = index.call_args.args[1]

        if considered is not None:
            raise AssertionError(
                f"Expected the whole repository considered, got {considered}."
            )

        return True

    return assertion


def _nothing_was_indexed(index: Any) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if index.call_args_list:
            raise AssertionError(f"Expected no indexing, got {index.call_args_list}.")

        return True

    return assertion


def _the_branch_asked_about_was(branch: Any, named: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        asked = branch.call_args

        if asked is None or asked.args[0:1] != (named,):
            raise AssertionError(f"Expected [{named}] asked about, got [{asked}].")

        return True

    return assertion


def _the_branch_was_not_asked_about(branch: Any) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        if branch.call_args_list:
            raise AssertionError(
                f"Expected the provider not to be asked, got {branch.call_args_list}."
            )

        return True

    return assertion


def _what_came_back_is(sha: str | None) -> Assertion[str | None]:
    def assertion(answered: str | None) -> bool:
        if answered != sha:
            raise AssertionError(f"Expected [{sha}] to come back, got [{answered}].")

        return True

    return assertion


def nothing_recorded() -> Any:
    """A repository nothing is on record about at all - a first deployment."""
    return create_autospec(IndexRecord, instance=True, return_value=None)


def an_index_at(indexed: str | None, pushed: str | None) -> Any:
    """The row as it stands: what the passages describe, and what was reported.

    Both are optional and mean different absences - no `indexed` is an index
    nobody has built, where no `pushed` is a repository nothing has told Argus
    about.
    """
    return create_autospec(
        IndexRecord,
        instance=True,
        return_value=RepositoryIndex(
            repository=THE_REPOSITORY, indexed_sha=indexed, pending_sha=pushed
        )
    )


def a_branch_at(sha: str) -> Any:
    return create_autospec(BranchHead, instance=True, return_value=sha)


def a_comparison_naming(*paths: str) -> Any:
    return create_autospec(ChangedPaths, instance=True, return_value=list(paths))


def a_comparison_that_cannot_say() -> Any:
    """More changed files than the provider will list, which is no answer."""
    return create_autospec(ChangedPaths, instance=True, return_value=None)


def an_indexer() -> Any:
    """A stand-in for the pass itself.

    The seam is the call rather than the store under it: what indexing does is
    asserted in this module's own component tests against a real Qdrant, and
    what belongs here is which commit it is aimed at and with which paths.
    """
    return create_autospec(Indexer, instance=True)


def some_settings(repository: str = THE_REPOSITORY,
                  base_branch: str = THE_DEPLOYED_BRANCH) -> IndexSettings:
    """What a pass is aimed at - the repository, and the branch that is running."""
    return IndexSettings(
        github_api_url="https://api.github.invalid",
        github_repository=repository,
        github_read_token="ghp_dont-care-read-token",
        github_source_paths="",
        github_base_branch=base_branch,
        code_index_collection="dont-care-collection",
        code_index_max_lines=DONT_CARE_MAX_LINES,
        code_index_chunk_overlap=DONT_CARE_OVERLAP
    )
