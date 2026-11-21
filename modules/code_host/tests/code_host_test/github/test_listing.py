"""What files a repository holds at a ref, and what one of them says.

The two primitives Code-Fix localizes a fault with. That is enough to find a bug
in a repository that fits in a context window, and it is deliberately *not*
enough for one that does not - which is the question the index exists to answer,
and which the benchmark is meant to settle rather than assert.

Credential-wise this stays a read: the token named here can read a repository
and cannot write to one, so the read tier's claim - that its process cannot
mutate - survives the repository arriving in it.

Which of the files are the service's own is not this module's to decide, so
every file the tree names comes back; the read tier scopes them.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.logs import one_record_was_logged
from argus_testkit.scenario import Scenario, attempting
from code_host import RepositoryUnreadable
from code_host.github.headers import (
    ACCEPT_HEADER,
    AUTHORIZATION_HEADER,
    BEARER_SCHEME,
    GITHUB_MEDIA_TYPE,
)
from code_host.github.listing import (
    CONTENT_FIELD,
    ENTRY_TYPE_FIELD,
    FILE_ENTRY_TYPE,
    PATH_FIELD,
    RECURSIVE_PARAMETER,
    RECURSIVELY,
    REF_FIELD,
    TREE_FIELD,
    TRUNCATED_FIELD,
    list_repository_files,
    read_repository_file,
)

from code_host_test.framework.settings import some_settings

DONT_CARE_REF = "main"
DONT_CARE_PATH = "src/io_shop/spend_summary.py"

# What GitHub calls a directory's entry in a tree. The module reads only files'
# entries, so it names no constant for this one.
A_DIRECTORY_ENTRY_TYPE = "tree"


@pytest.mark.unit
def test_the_files_of_a_repository_are_listed_from_the_ref_asked_about() -> None:
    some_ref = "main"
    repository = a_repository_holding(
        "src/io_shop/spend_summary.py", "src/io_shop/accounts.py"
    )

    Scenario() \
        .when(
            lambda: list_repository_files(some_ref, some_settings(), repository.get)
        ) \
        .then(
            all_of(
                _the_files_listed_are(
                    ["src/io_shop/spend_summary.py", "src/io_shop/accounts.py"]
                ),
                _a_request_ended_with(repository, f"/git/trees/{some_ref}")
            )
        )


@pytest.mark.unit
def test_the_tree_is_asked_for_whole_rather_than_one_directory_deep() -> None:
    # Asked one level deep, GitHub names a directory's files and stops - and a
    # model is told a file one directory down is not in the repository.
    repository = a_repository_holding("src/io_shop/spend_summary.py")

    Scenario() \
        .when(
            lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
        ) \
        .then(_the_request_was_asked_with(repository, RECURSIVE_PARAMETER, RECURSIVELY))


@pytest.mark.unit
def test_a_listing_asks_for_the_api_s_own_media_type() -> None:
    # Without it GitHub answers in its default, which it is free to change
    # under this reader.
    repository = a_repository_holding("src/io_shop/spend_summary.py")

    Scenario() \
        .when(
            lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
        ) \
        .then(_the_request_accepted(repository, GITHUB_MEDIA_TYPE))


@pytest.mark.unit
def test_a_file_read_asks_for_the_api_s_own_media_type() -> None:
    repository = a_repository_whose_file_says("dont care source")

    Scenario() \
        .when(
            lambda: read_repository_file(DONT_CARE_PATH, DONT_CARE_REF, some_settings(),
                                         repository.get)
        ) \
        .then(_the_request_accepted(repository, GITHUB_MEDIA_TYPE))


@pytest.mark.unit
def test_every_file_the_repository_holds_is_listed_whatever_directory_it_is_in() -> None:
    # Which directories hold the service is the deployment's to say and the read
    # tier's to apply; a host that decided it would be a second place deciding.
    repository = a_repository_holding(
        "src/io_shop/spend_summary.py", "src/target_app/scenarios.py", "README.md"
    )

    Scenario() \
        .when(
            lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
        ) \
        .then(_the_files_listed_are(
            ["src/io_shop/spend_summary.py", "src/target_app/scenarios.py", "README.md"]
        ))


@pytest.mark.unit
def test_the_directories_a_repository_contains_are_not_listed_as_files() -> None:
    # The tree answers with both, and a directory is not something anyone can
    # read. Offering one as a file would have Code-Fix spend a call to be told
    # so, and spend it again on the next directory.
    repository = a_repository_holding("src/io_shop/spend_summary.py")
    repository.get.return_value = _a_tree_answer(
        blobs=["src/io_shop/spend_summary.py"], trees=["src", "src/io_shop"]
    )

    Scenario() \
        .when(
            lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
        ) \
        .then(
            all_of(
                _the_files_listed_are(["src/io_shop/spend_summary.py"])
            )
        )


@pytest.mark.unit
def test_a_listing_the_repository_could_not_finish_is_not_offered_as_the_whole() -> None:
    # THE ONE THAT MATTERS ON A BIG REPOSITORY. The API truncates a tree it
    # considers too large and says so in a flag beside the entries. A truncated
    # listing read as complete would have Code-Fix conclude that the file it
    # needs does not exist - absence of evidence arriving as evidence of
    # absence, which is the failure this codebase refuses everywhere else.
    repository = a_repository_holding("src/io_shop/spend_summary.py")
    repository.get.return_value = _a_tree_answer(
        blobs=["src/io_shop/spend_summary.py"], truncated=True
    )

    Scenario() \
        .when(
            attempting(
                lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable)
            )
        )


@pytest.mark.unit
def test_a_listing_the_repository_could_not_finish_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A repository grown past what the API will list, which no retry fixes and
    # which only somebody reading this tier's log would learn.
    repository = a_repository_holding("src/io_shop/spend_summary.py")
    repository.get.return_value = _a_tree_answer(
        blobs=["src/io_shop/spend_summary.py"], truncated=True
    )

    Scenario() \
        .when(
            attempting(
                lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
            )
        ) \
        .then(
            one_record_was_logged(caplog, "code_host.github.listing", logging.WARNING,
                                  "repository listing truncated",
                                  values={"ref": DONT_CARE_REF})
        )


@pytest.mark.unit
def test_an_unreachable_repository_is_not_reported_as_an_empty_one() -> None:
    repository = a_repository_holding("dont/care.py")
    repository.get.side_effect = httpx2.ConnectError("connection refused")

    Scenario() \
        .when(
            attempting(
                lambda: list_repository_files(DONT_CARE_REF, some_settings(), repository.get)
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable)
            )
        )


@pytest.mark.unit
def test_a_file_is_read_as_the_text_it_holds() -> None:
    some_source = "def average_spend_per_item_this_month(account):\n    return 0\n"
    repository = a_repository_whose_file_says(some_source)

    Scenario() \
        .when(
            lambda: read_repository_file(
                DONT_CARE_PATH, DONT_CARE_REF, some_settings(), repository.get
            )
        ) \
        .then(
            all_of(
                _the_file_read_says(some_source)
            )
        )


@pytest.mark.unit
def test_a_file_is_read_from_the_path_and_ref_asked_about() -> None:
    some_path = "src/io_shop/spend_summary.py"
    some_ref = "main"
    repository = a_repository_whose_file_says("dont care source")

    Scenario() \
        .when(
            lambda: read_repository_file(some_path, some_ref, some_settings(), repository.get)
        ) \
        .then(
            all_of(
                _a_request_ended_with(repository, f"/contents/{some_path}"),
                _the_request_named_the_ref(repository, some_ref)
            )
        )


@pytest.mark.unit
def test_the_repository_is_read_under_a_credential_that_cannot_write() -> None:
    # The read tier's whole claim, restated for a new channel: this process
    # holds nothing that could change the repository it is reading. A token
    # that could push would make `argus-read-mcp` capable of mutation, which is
    # the one thing the tier split exists to prevent (§13).
    some_read_token = "ghp_some-read-only-token"
    repository = a_repository_whose_file_says("dont care source")

    Scenario() \
        .when(
            lambda: read_repository_file(
                DONT_CARE_PATH,
                DONT_CARE_REF,
                some_settings(read_token=some_read_token),
                repository.get
            )
        ) \
        .then(
            all_of(
                _the_request_was_authorized_with(
                    repository, f"{BEARER_SCHEME} {some_read_token}"
                )
            )
        )


@pytest.mark.unit
def test_a_repository_read_with_no_credential_configured_carries_none() -> None:
    # A public repository reads without one. "Bearer" with nothing after it is
    # refused before the request leaves, so every read failed wherever the
    # token was left unset - CI's included.
    repository = a_repository_whose_file_says("dont care source")

    Scenario() \
        .when(
            lambda: read_repository_file(
                DONT_CARE_PATH, DONT_CARE_REF, some_settings(read_token=""), repository.get
            )
        ) \
        .then(
            all_of(
                _the_request_was_authorized_with(repository, None)
            )
        )


@pytest.mark.unit
def test_a_file_that_is_not_there_is_said_to_be_missing_rather_than_empty() -> None:
    # An empty string is a file that exists and says nothing, which is a real
    # thing a repository can hold. A model handed one for a path that does not
    # exist would conclude the module is empty and write a fix for a file that
    # is not the file.
    repository = a_repository_whose_file_says("dont care source")
    repository.get.return_value = httpx2.Response(
        status_code=404,
        json={"message": "Not Found"},
        request=httpx2.Request("GET", "http://github.invalid/")
    )

    Scenario() \
        .when(
            attempting(
                lambda: read_repository_file(
                    DONT_CARE_PATH, DONT_CARE_REF, some_settings(), repository.get
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable)
            )
        )


@pytest.mark.unit
def test_a_file_that_is_not_text_is_refused_rather_than_mangled() -> None:
    # A repository holds images and archives as well as source. Decoding one as
    # UTF-8 either raises somewhere unhelpful or produces replacement
    # characters that reach a model as though they were code.
    repository = a_repository_whose_file_says("dont care source")
    repository.get.return_value = httpx2.Response(
        status_code=200,
        json={CONTENT_FIELD: base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()},
        request=httpx2.Request("GET", "http://github.invalid/")
    )

    Scenario() \
        .when(
            attempting(
                lambda: read_repository_file(
                    "docs/diagram.png", DONT_CARE_REF, some_settings(), repository.get
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable)
            )
        )


def _the_files_listed_are(paths: list[str]) -> Assertion[Any]:
    def assertion(listed: Any) -> bool:
        if list(listed) != paths:
            raise AssertionError(f"Expected the files {paths}, got {list(listed)}.")

        return True

    return assertion


def _the_file_read_says(source: str) -> Assertion[Any]:
    def assertion(read: Any) -> bool:
        if read != source:
            raise AssertionError(f"Expected [{source!r}], got [{read!r}].")

        return True

    return assertion


def _a_request_ended_with(repository: _Repository, path: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [made.args[0] for made in repository.get.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def _the_request_named_the_ref(repository: _Repository, ref: str) -> Assertion[Any]:
    return _the_request_was_asked_with(repository, REF_FIELD, ref)


def _the_request_was_asked_with(repository: _Repository,
                                parameter: str,
                                value: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        asked = repository.get.call_args.kwargs.get("params", {}).get(parameter)

        if asked != value:
            raise AssertionError(
                f"Expected the request to ask with [{parameter}] as [{value}], got [{asked}]."
            )

        return True

    return assertion


def _the_request_was_authorized_with(repository: _Repository,
                                     credential: str | None) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        sent = repository.get.call_args.kwargs["headers"].get(AUTHORIZATION_HEADER)

        if sent != credential:
            raise AssertionError(
                f"Expected the read to authorize with [{credential}], got [{sent}]."
            )

        return True

    return assertion


def _the_request_accepted(repository: _Repository, media_type: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        accepted = repository.get.call_args.kwargs["headers"].get(ACCEPT_HEADER)

        if accepted != media_type:
            raise AssertionError(
                f"Expected the read to accept [{media_type}], it asked for [{accepted}]."
            )

        return True

    return assertion


def _a_tree_answer(blobs: list[str],
                   trees: list[str] | None = None,
                   truncated: bool = False) -> httpx2.Response:
    return httpx2.Response(
        status_code=200,
        json={
            TRUNCATED_FIELD: truncated,
            TREE_FIELD: [
                *({PATH_FIELD: path, ENTRY_TYPE_FIELD: A_DIRECTORY_ENTRY_TYPE}
                  for path in trees or []),
                *({PATH_FIELD: path, ENTRY_TYPE_FIELD: FILE_ENTRY_TYPE} for path in blobs)
            ]
        },
        request=httpx2.Request("GET", "http://github.invalid/")
    )


class _Repository:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx2.get)


def a_repository_holding(*paths: str) -> _Repository:
    repository = _Repository()
    repository.get.return_value = _a_tree_answer(blobs=list(paths))

    return repository


def a_repository_whose_file_says(source: str) -> _Repository:
    repository = _Repository()
    repository.get.return_value = httpx2.Response(
        status_code=200,
        json={CONTENT_FIELD: base64.b64encode(source.encode()).decode()},
        request=httpx2.Request("GET", "http://github.invalid/")
    )

    return repository
