"""Reading the Target Service's own source (spec §7.4, §12.1, §13).

The read tier's fourth channel, and the one Code-Fix localizes a fault in. Two
primitives and no more: what files there are, and what one of them says. That is
enough to find a bug in a repository that fits in a context window, and it is
deliberately *not* enough for one that does not - which is the question the RAG
retriever behind the same seam exists to answer, and which the benchmark is
meant to settle rather than assert.

Credential-wise this stays a read: the token named here can read a repository
and cannot write to one, so the tier's claim - that this process cannot mutate -
survives the repository arriving in it.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import create_autospec

import httpx
import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.repository import (
    RepositoryReadSettings,
    RepositoryUnreadable,
    list_repository_files,
    read_repository_file,
)

DONT_CARE_REF = "main"
DONT_CARE_PATH = "src/io_shop/spend_summary.py"


@pytest.mark.unit
def test_the_files_of_a_repository_are_listed_from_the_ref_asked_about() -> None:
    some_ref = "main"
    repository = a_repository_holding(
        "src/io_shop/spend_summary.py", "src/io_shop/accounts.py"
    )

    Scenario() \
        .when(
            lambda: list_repository_files(
                ref=some_ref, settings=some_settings(), get=repository.get
            )
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
            lambda: list_repository_files(
                ref=DONT_CARE_REF, settings=some_settings(), get=repository.get
            )
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
                lambda: list_repository_files(
                    ref=DONT_CARE_REF, settings=some_settings(), get=repository.get
                )
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
                path=DONT_CARE_PATH,
                ref=DONT_CARE_REF,
                settings=some_settings(),
                get=repository.get
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
            lambda: read_repository_file(
                path=some_path,
                ref=some_ref,
                settings=some_settings(),
                get=repository.get
            )
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
                path=DONT_CARE_PATH,
                ref=DONT_CARE_REF,
                settings=some_settings(read_token=some_read_token),
                get=repository.get
            )
        ) \
        .then(
            all_of(
                _the_request_was_authorized_with(
                    repository, f"Bearer {some_read_token}"
                )
            )
        )


@pytest.mark.unit
def test_a_file_that_is_not_there_is_said_to_be_missing_rather_than_empty() -> None:
    # An empty string is a file that exists and says nothing, which is a real
    # thing a repository can hold. A model handed one for a path that does not
    # exist would conclude the module is empty and write a fix for a file that
    # is not the file.
    repository = a_repository_whose_file_says("dont care source")
    repository.get.return_value = httpx.Response(
        status_code=404,
        json={"message": "Not Found"},
        request=httpx.Request("GET", "http://github.invalid/")
    )

    Scenario() \
        .when(
            attempting(
                lambda: read_repository_file(
                    path=DONT_CARE_PATH,
                    ref=DONT_CARE_REF,
                    settings=some_settings(),
                    get=repository.get
                )
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(RepositoryUnreadable)
            )
        )


@pytest.mark.unit
def test_an_unreachable_repository_is_not_reported_as_an_empty_one() -> None:
    repository = a_repository_holding("dont/care.py")
    repository.get.side_effect = httpx.ConnectError("connection refused")

    Scenario() \
        .when(
            attempting(
                lambda: list_repository_files(
                    ref=DONT_CARE_REF, settings=some_settings(), get=repository.get
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
    repository.get.return_value = httpx.Response(
        status_code=200,
        json={"content": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()},
        request=httpx.Request("GET", "http://github.invalid/")
    )

    Scenario() \
        .when(
            attempting(
                lambda: read_repository_file(
                    path="docs/diagram.png",
                    ref=DONT_CARE_REF,
                    settings=some_settings(),
                    get=repository.get
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
    def assertion(_: Any) -> bool:
        named = repository.get.call_args.kwargs.get("params", {}).get("ref")

        if named != ref:
            raise AssertionError(f"Expected the read at ref [{ref}], got [{named}].")

        return True

    return assertion


def _the_request_was_authorized_with(repository: _Repository,
                                     credential: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        sent = repository.get.call_args.kwargs["headers"].get("Authorization")

        if sent != credential:
            raise AssertionError(
                f"Expected the read to authorize with [{credential}], got [{sent}]."
            )

        return True

    return assertion


def _a_tree_answer(blobs: list[str],
                   trees: list[str] | None = None,
                   truncated: bool = False) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={
            "truncated": truncated,
            "tree": [
                *({"path": path, "type": "tree"} for path in trees or []),
                *({"path": path, "type": "blob"} for path in blobs)
            ]
        },
        request=httpx.Request("GET", "http://github.invalid/")
    )


class _Repository:
    def __init__(self) -> None:
        self.get: Any = create_autospec(httpx.get)


def a_repository_holding(*paths: str) -> _Repository:
    repository = _Repository()
    repository.get.return_value = _a_tree_answer(blobs=list(paths))

    return repository


def a_repository_whose_file_says(source: str) -> _Repository:
    repository = _Repository()
    repository.get.return_value = httpx.Response(
        status_code=200,
        json={"content": base64.b64encode(source.encode()).decode()},
        request=httpx.Request("GET", "http://github.invalid/")
    )

    return repository


def some_settings(api_url: str = "https://api.github.invalid",
                  repository: str = "dont-care/dont-care",
                  read_token: str = "ghp_dont-care-read-token"
                  ) -> RepositoryReadSettings:
    """The slice this tier reads source under.

    Distinct from the write tier's although both name the same repository: this
    one holds a credential that can only read, and that difference is the tier
    boundary rather than a naming preference.
    """
    return RepositoryReadSettings(
        github_api_url=api_url,
        github_repository=repository,
        github_read_token=read_token
    )
