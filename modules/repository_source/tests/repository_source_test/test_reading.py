"""A repository's source, read whole at a commit.

What two modules would otherwise each have to know about GitHub: that a
repository arrives as one tarball, that everything inside it is wrapped in a
directory named for the commit, and that an entry which is not text is to be
passed over rather than refused.

The prefix is the part worth watching. GitHub names the wrapping directory after
the owner, the repository and the commit, so every path arrives with something
nobody asked for on the front of it - and a path reported that way sends a
reader to a file that does not exist, in a repository where it plainly does.

Everything here is driven through an injected `get`, so the suite exercises the
real unpacking against a real archive without a network or a credential.
"""

from __future__ import annotations

import io
import tarfile
from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from repository_source import (
    RepositorySourceSettings,
    RepositoryUnreadable,
    the_source_at,
)

SOME_REF = "cbe7bc3"
SOME_PATH = "src/io_shop/spend_summary.py"
ANOTHER_PATH = "src/io_shop/accounts.py"

SOME_SOURCE = "def spend_summary() -> None: ...\n"

# What GitHub wraps an archive in: the owner, the repository and the commit it
# was cut at. Nothing outside the archive accepts a path spelled this way.
SOME_ARCHIVE_PREFIX = "owner-repo-77296ac"


@pytest.mark.unit
def test_every_file_comes_back_under_its_own_path() -> None:
    Scenario() \
        .given(
            some_repository := _a_repository_whose_source_is({
                SOME_PATH: SOME_SOURCE,
                ANOTHER_PATH: "def accounts() -> None: ...\n"
            })
        ) \
        .when(
            lambda: the_source_at(
                SOME_REF, _some_settings(), some_repository.get
            )
        ) \
        .then(
            all_of(
                _it_holds(SOME_PATH, SOME_SOURCE),
                _it_holds(ANOTHER_PATH, "def accounts() -> None: ...\n")
            )
        )


@pytest.mark.unit
def test_the_archives_own_wrapping_directory_is_not_part_of_a_path() -> None:
    # The prefix GitHub adds. A path reported with it on the front names a file
    # that does not exist, and the tool looks broken rather than mis-prefixed.
    Scenario() \
        .given(
            some_repository := _a_repository_whose_source_is({SOME_PATH: SOME_SOURCE})
        ) \
        .when(
            lambda: the_source_at(
                SOME_REF, _some_settings(), some_repository.get
            )
        ) \
        .then(_no_path_begins_with(SOME_ARCHIVE_PREFIX))


@pytest.mark.unit
def test_a_file_that_is_not_text_is_passed_over_rather_than_refused() -> None:
    # A repository is allowed to hold a logo. Refusing the whole read over one
    # would make search and indexing impossible in every repository that has
    # one, and an image is not somewhere a matching line can be anyway.
    Scenario() \
        .given(
            some_repository := _a_repository_whose_source_is(
                {SOME_PATH: SOME_SOURCE},
                and_something_that_is_not_text={"logo.png": b"\xff\xd8\xff\xe0"}
            )
        ) \
        .when(
            lambda: the_source_at(
                SOME_REF, _some_settings(), some_repository.get
            )
        ) \
        .then(
            all_of(
                _it_holds(SOME_PATH, SOME_SOURCE),
                _it_says_nothing_about("logo.png")
            )
        )


@pytest.mark.unit
def test_a_repository_that_could_not_be_fetched_is_refused_rather_than_empty() -> None:
    # "The repository has no files" and "I could not read the repository" are
    # opposite things, and an empty answer would have a caller conclude the
    # first while the second happened.
    some_repository = _a_repository()
    some_repository.get.side_effect = httpx.ConnectError("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: the_source_at(
                    SOME_REF, _some_settings(), some_repository.get
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_the_source_is_read_under_a_credential_that_cannot_write() -> None:
    # The tier boundary, as a fact about what is sent rather than about what
    # the caller intended. This token reads source and cannot push.
    some_repository = _a_repository_whose_source_is({SOME_PATH: SOME_SOURCE})
    the_read_only_token = "ghp_a-token-that-only-reads"

    Scenario() \
        .given(the_settings := _some_settings(read_token=the_read_only_token)) \
        .when(
            lambda: the_source_at(SOME_REF, the_settings, some_repository.get)
        ) \
        .then(_it_was_asked_bearing(some_repository, the_read_only_token))


@pytest.mark.unit
def test_the_commit_asked_about_is_the_one_fetched() -> None:
    # An index is a claim about one commit. Reading a different one and saying
    # otherwise is how an index comes to describe code nobody is running.
    some_repository = _a_repository_whose_source_is({SOME_PATH: SOME_SOURCE})

    Scenario() \
        .when(
            lambda: the_source_at(SOME_REF, _some_settings(), some_repository.get)
        ) \
        .then(_it_asked_for_a_url_naming(some_repository, SOME_REF))


class _Repository:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx.get)


def _a_repository() -> _Repository:
    return _Repository()


def _a_repository_whose_source_is(
    files: dict[str, str],
    and_something_that_is_not_text: dict[str, bytes] | None = None
) -> _Repository:
    repository = _Repository()
    repository.get.return_value = _an_archive_of(
        {path: source.encode() for path, source in files.items()}
        | (and_something_that_is_not_text or {})
    )

    return repository


def _an_archive_of(entries: dict[str, bytes]) -> httpx.Response:
    """The repository as GitHub serves it whole - one gzipped tar, one request.

    Built rather than stubbed, so what the tests exercise is the real unpacking
    against a real archive. The wrapping prefix is put on here because GitHub
    puts it on there, and stripping it is part of what is under test.
    """
    archive = io.BytesIO()

    with tarfile.open(fileobj=archive, mode="w:gz") as writing:
        for path, held in entries.items():
            entry = tarfile.TarInfo(f"{SOME_ARCHIVE_PREFIX}/{path}")
            entry.size = len(held)
            writing.addfile(entry, io.BytesIO(held))

    return httpx.Response(
        status_code=httpx.codes.OK,
        content=archive.getvalue(),
        request=httpx.Request("GET", "http://github.invalid/")
    )


def _some_settings(
    api_url: str = "https://api.github.invalid",
    repository: str = "dont-care/dont-care",
    read_token: str = "ghp_dont-care-read-token"
) -> RepositorySourceSettings:
    return RepositorySourceSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=read_token
    )


def _it_holds(path: str, source: str) -> Assertion[dict[str, str]]:
    def it_holds(read: dict[str, str]) -> bool:
        if read.get(path) != source:
            raise AssertionError(
                f"Expected [{path}] to read [{source!r}], and it read "
                f"[{read.get(path)!r}]. What came back named "
                f"{sorted(read)}."
            )

        return True

    return it_holds


def _it_says_nothing_about(path: str) -> Assertion[dict[str, str]]:
    def it_says_nothing_about(read: dict[str, str]) -> bool:
        if path in read:
            raise AssertionError(
                f"Expected [{path}] to be passed over, and it came back."
            )

        return True

    return it_says_nothing_about


def _no_path_begins_with(prefix: str) -> Assertion[dict[str, str]]:
    def no_path_begins_with(read: dict[str, str]) -> bool:
        wearing_it = [path for path in read if path.startswith(prefix)]

        if wearing_it:
            raise AssertionError(
                f"Expected no path to begin with [{prefix}], and "
                f"{wearing_it} did."
            )

        return True

    return no_path_begins_with


def _it_was_asked_bearing(repository: _Repository,
                          token: str) -> Assertion[dict[str, str]]:
    def it_was_asked_bearing(_: dict[str, str]) -> bool:
        headers = repository.get.call_args.kwargs["headers"]

        if headers.get("Authorization") != f"Bearer {token}":
            raise AssertionError(
                f"Expected the read to bear [{token}], and it bore "
                f"[{headers.get('Authorization')}]."
            )

        return True

    return it_was_asked_bearing


def _it_asked_for_a_url_naming(repository: _Repository,
                               ref: str) -> Assertion[dict[str, str]]:
    def it_asked_for_a_url_naming(_: dict[str, str]) -> bool:
        asked = repository.get.call_args.args[0]

        if not asked.endswith(f"/{ref}"):
            raise AssertionError(
                f"Expected the read to ask for the archive at [{ref}], "
                f"and it asked for [{asked}]."
            )

        return True

    return it_asked_for_a_url_naming
