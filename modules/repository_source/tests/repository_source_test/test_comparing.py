"""What changed between two commits, as paths (spec §11).

The question a reconciler asks so it does not have to consider a repository
entire. Everything unchanged is already in the index under an id derived from
what it says, so a full pass embeds nothing it has seen before - but it still
asks the store, once per file, whether it holds it. At forty files that is
free; at a hundred thousand it is a hundred thousand round trips a cycle, and
this is what turns them into the handful that moved.

Two answers that are not the same and must never be confused: nothing changed,
and I cannot tell you what changed. GitHub lists at most three hundred files
for a comparison and says nothing about having stopped there, so a list at that
ceiling is not a list - and a caller handed it as though it were would index
three hundred files and leave the rest of a large push silently unindexed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit.assertions import Assertion, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from repository_source import RepositorySourceSettings, RepositoryUnreadable
from repository_source.comparing import (
    MOST_FILES_A_COMPARISON_LISTS,
    paths_changed_between,
)

AN_EARLIER_COMMIT = "3f1b9d2c8a7e6f5d4c3b2a1908f7e6d5c4b3a291"
THE_COMMIT_PUSHED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"

DONT_CARE_BASE = AN_EARLIER_COMMIT
DONT_CARE_HEAD = THE_COMMIT_PUSHED

SOME_FILE_EDITED = "src/io_shop/spend_summary.py"
SOME_FILE_ADDED = "src/io_shop/discounts.py"
SOME_FILE_DELETED = "src/io_shop/old_discounts.py"
SOME_FILE_RENAMED_FROM = "src/io_shop/summaries.py"
SOME_FILE_RENAMED_TO = "src/io_shop/spending.py"

# A template rather than a path: the only test that uses it wants three
# hundred distinct files and cares about nothing else about them.
A_NUMBERED_MODULE = "src/io_shop/module_{number}.py"


@pytest.mark.unit
def test_the_files_a_comparison_names_come_back_as_paths() -> None:
    compared = a_comparison_of(
        {"filename": SOME_FILE_EDITED, "status": "modified"},
        {"filename": SOME_FILE_ADDED, "status": "added"}
    )

    Scenario() \
        .when(
            lambda: paths_changed_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_paths_changed_are([
            SOME_FILE_EDITED, SOME_FILE_ADDED
        ]))


@pytest.mark.unit
def test_a_file_that_was_deleted_is_named_so_it_can_be_forgotten() -> None:
    # The path is what a re-index is driven by, and a deleted file is the one
    # case that has no source to re-read. Left out, its passages stay in the
    # store and go on being retrieved for code that is not there any more.
    compared = a_comparison_of(
        {"filename": SOME_FILE_DELETED, "status": "removed"}
    )

    Scenario() \
        .when(
            lambda: paths_changed_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_paths_changed_are([SOME_FILE_DELETED]))


@pytest.mark.unit
def test_a_renamed_file_names_both_where_it_was_and_where_it_is() -> None:
    # A rename is a deletion and an addition wearing one entry. Named only by
    # its new path, the passages under the old one are never forgotten - and
    # the index answers with a file the repository no longer has.
    compared = a_comparison_of({
        "filename": SOME_FILE_RENAMED_TO,
        "status": "renamed",
        "previous_filename": SOME_FILE_RENAMED_FROM
    })

    Scenario() \
        .when(
            lambda: paths_changed_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_paths_changed_are([
            SOME_FILE_RENAMED_TO, SOME_FILE_RENAMED_FROM
        ]))


@pytest.mark.unit
def test_two_commits_with_nothing_between_them_changed_nothing() -> None:
    # An empty list is an answer: there is no work. Distinct from not being
    # able to say, which is the next test and means the opposite.
    compared = a_comparison_of()

    Scenario() \
        .when(
            lambda: paths_changed_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_paths_changed_are([]))


@pytest.mark.unit
def test_a_comparison_too_large_to_list_says_it_cannot_say() -> None:
    # THE ONE THAT MATTERS ON A BIG PUSH. GitHub lists at most three hundred
    # files for a comparison and gives no flag saying it stopped - the answer
    # arrives well-formed, complete-looking and short. Read as complete, a
    # rebase or a formatting sweep leaves most of the repository unindexed
    # while the watermark records the index as current.
    compared = a_comparison_of(*(
        {"filename": A_NUMBERED_MODULE.format(number=number), "status": "modified"}
        for number in range(MOST_FILES_A_COMPARISON_LISTS)
    ))

    Scenario() \
        .when(
            lambda: paths_changed_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_nothing_can_be_said_about_what_changed())


@pytest.mark.unit
def test_a_comparison_that_could_not_be_made_raises() -> None:
    # Not an empty list. "Nothing changed" would have the reconciler record
    # the index as current over passages nobody updated, which is the one
    # outcome the watermark exists to prevent.
    refused = create_autospec(httpx.get)
    refused.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: paths_changed_between(
                    DONT_CARE_BASE,
                    DONT_CARE_HEAD,
                    some_settings(),
                    get=refused
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_the_comparison_asked_for_is_the_one_between_the_two_commits() -> None:
    # Ordered, and it matters: reversed, the comparison describes undoing the
    # push rather than making it.
    compared = a_comparison_of()

    Scenario() \
        .when(
            lambda: paths_changed_between(
                AN_EARLIER_COMMIT,
                THE_COMMIT_PUSHED,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_request_ended_with(
            compared, f"/compare/{AN_EARLIER_COMMIT}...{THE_COMMIT_PUSHED}"
        ))


def _the_paths_changed_are(paths: list[str]) -> Assertion[list[str] | None]:
    """Which files a pass has to reconsider, and no others."""
    def assertion(changed: list[str] | None) -> bool:
        if changed is None or sorted(changed) != sorted(paths):
            raise AssertionError(f"Expected the paths {sorted(paths)}, got {changed}.")

        return True

    return assertion


def _nothing_can_be_said_about_what_changed() -> Assertion[list[str] | None]:
    """The answer that means "consider the whole repository"."""
    def assertion(changed: list[str] | None) -> bool:
        if changed is not None:
            raise AssertionError(
                f"Expected no answer about what changed, got {changed}."
            )

        return True

    return assertion


def _the_request_ended_with(compared: Any, path: str) -> Assertion[Any]:
    def assertion(dont_care_result: Any) -> bool:
        addressed = [made.args[0] for made in compared.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def a_comparison_of(*files: dict[str, str]) -> Any:
    """GitHub's answer for two commits, carrying the entries it lists."""
    compared = create_autospec(httpx.get)
    compared.return_value = httpx.Response(
        status_code=200,
        json={"files": list(files)},
        request=httpx.Request("GET", "http://github.invalid/")
    )

    return compared


def some_settings(api_url: str = "https://api.github.invalid",
                  repository: str = "dont-care/dont-care",
                  read_token: str = "ghp_dont-care-read-token"
                  ) -> RepositorySourceSettings:
    """What is needed to read a repository, and nothing that could change one."""
    return RepositorySourceSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=read_token
    )
