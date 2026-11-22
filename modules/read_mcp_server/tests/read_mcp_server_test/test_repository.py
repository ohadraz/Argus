"""Reading the Target Service's own source (spec §7.4, §12.1, §13).

The read tier's fourth channel, and the one Code-Fix localizes a fault in. What
files there are, and every line matching what the investigation named - each
scoped to the directories that hold the service, which is this module's own.
What the repository holds is the code host's answer and is asserted against
GitHub's wire shape in `code_host`; here it is a port answering with files.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.scenario import Scenario, attempting
from code_host import CodeHostReads, RepositoryUnreadable
from core.models import CodeOutsideThePatch, CodeUse
from read_mcp_server.outside_the_patch import code_outside_the_patch
from read_mcp_server.repository import (
    RepositoryReadSettings,
    list_repository_files,
    read_code_outside_the_patch,
    search_repository,
)

DONT_CARE_REF = "main"


@pytest.mark.unit
def test_the_files_of_a_repository_are_listed_from_the_ref_asked_about() -> None:
    some_ref = "main"
    code = a_code_host_listing("src/io_shop/spend_summary.py", "src/io_shop/accounts.py")

    Scenario() \
        .when(
            lambda: list_repository_files(some_ref, some_settings(), code=code)
        ) \
        .then(
            all_of(
                _the_files_listed_are(
                    ["src/io_shop/spend_summary.py", "src/io_shop/accounts.py"]
                ),
                _the_files_were_listed_at(code, some_ref)
            )
        )


@pytest.mark.unit
def test_only_the_service_s_own_source_is_listed() -> None:
    # A repository holds more than the service. This one carries the harness
    # that stages incidents against the shop, and a fix agent reading that is
    # reading the rig rather than the product - it learns how its own incidents
    # are generated, which is neither its business nor any help.
    #
    # Scoped by configuration rather than by a rule, because which directories
    # hold the service is a fact about a deployment: point Argus at a repository
    # that is nothing but the service and the whole of it is in scope.
    code = a_code_host_listing(
        "src/io_shop/spend_summary.py",
        "src/target_app/scenarios.py",
        "README.md"
    )

    Scenario() \
        .when(
            lambda: list_repository_files(
                DONT_CARE_REF, some_settings(source_paths="src/io_shop"), code=code
            )
        ) \
        .then(_the_files_listed_are(["src/io_shop/spend_summary.py"]))


@pytest.mark.unit
def test_a_deployment_that_scopes_nothing_sees_the_whole_repository() -> None:
    # The honest default. A repository that is only the service needs no scope,
    # and one configured with none must not quietly answer as though it had been
    # given an empty list of directories.
    code = a_code_host_listing("src/io_shop/spend_summary.py", "README.md")

    Scenario() \
        .when(
            lambda: list_repository_files(
                DONT_CARE_REF, some_settings(source_paths=""), code=code
            )
        ) \
        .then(_the_files_listed_are(
            ["src/io_shop/spend_summary.py", "README.md"]
        ))


@pytest.mark.unit
def test_a_listing_the_code_host_refused_is_refused_rather_than_empty() -> None:
    # A listing missing files reads as a repository without them.
    code = create_autospec(CodeHostReads, instance=True)
    code.files_at.side_effect = RepositoryUnreadable("listing truncated")

    Scenario() \
        .when(
            attempting(
                lambda: list_repository_files(DONT_CARE_REF, some_settings(), code=code)
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_the_source_is_searched_for_what_the_investigation_named() -> None:
    # The whole reason this channel exists. Code-Fix is handed a cause - a flag
    # name, a function, a message - and without a way to ask where that appears
    # it can only open files by guessing at their names. It did: twelve turns
    # of reading, and it never reached the file the fault was in.
    the_flag = "monthly-spend-feature"
    code = a_code_host_whose_source_is({
        "src/io_shop/spend_summary.py": f"# ships behind the `{the_flag}` flag\n",
        "src/io_shop/accounts.py": "def accounts() -> None: ...\n"
    })

    Scenario() \
        .when(
            lambda: search_repository(the_flag, DONT_CARE_REF, some_settings(), code=code)
        ) \
        .then(
            all_of(
                _exactly_these_files_matched(["src/io_shop/spend_summary.py"]),
                _a_hit_quotes(the_flag)
            )
        )


@pytest.mark.unit
def test_a_hit_says_where_in_the_file_it_is() -> None:
    # A path alone sends the model back to reading the whole file, which is the
    # cost this tool exists to remove. The line number and the line itself are
    # what let it decide whether the file is worth opening at all.
    code = a_code_host_whose_source_is({
        "src/io_shop/spend_summary.py": "first\nsecond\nthe flag is here\nfourth\n"
    })

    Scenario() \
        .when(
            lambda: search_repository("the flag is here", DONT_CARE_REF, some_settings(),
                                      code=code)
        ) \
        .then(_a_hit_reads("src/io_shop/spend_summary.py:3: the flag is here"))


@pytest.mark.unit
def test_a_search_that_matches_nothing_is_an_answer_and_not_a_failure() -> None:
    # Unlike a listing that came back short, "that string is not in this
    # repository" is a fact about the repository and a useful one: it is how
    # the model learns the cause is not where it thought.
    code = a_code_host_whose_source_is({"src/io_shop/accounts.py": "nothing\n"})

    Scenario() \
        .when(
            lambda: search_repository("a string that is not there", DONT_CARE_REF,
                                      some_settings(), code=code)
        ) \
        .then(_exactly_these_files_matched([]))


@pytest.mark.unit
def test_a_repository_that_could_not_be_fetched_is_refused_rather_than_empty() -> None:
    # No matches and could-not-look are the same answer to a model and opposite
    # facts about the world. Silent, the second one teaches it the cause is not
    # in the code, which is the conclusion this whole change exists to stop
    # being reached by accident.
    code = create_autospec(CodeHostReads, instance=True)
    code.source_at.side_effect = RepositoryUnreadable("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: search_repository("dont care", DONT_CARE_REF, some_settings(),
                                          code=code)
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_a_search_answers_only_from_the_service_s_own_source() -> None:
    # The same scope, and it matters more here: the harness describes in prose
    # what it stages, so a search for the cause finds the harness explaining the
    # cause. What comes back would be the answer rather than the evidence.
    code = a_code_host_whose_source_is({
        "src/io_shop/spend_summary.py": "the flag guards this\n",
        "src/target_app/scenarios.py": "the flag breaks the page on purpose\n"
    })

    Scenario() \
        .when(
            lambda: search_repository(
                "the flag",
                DONT_CARE_REF,
                some_settings(source_paths="src/io_shop"),
                code=code
            )
        ) \
        .then(_exactly_these_files_matched(["src/io_shop/spend_summary.py"]))


@pytest.mark.unit
def test_the_code_outside_a_patch_is_read_off_the_services_own_source_at_the_ref() -> None:
    # The rig that stages incidents is not where the patch's readers live, for
    # the reason a search does not answer from it.
    some_ref = "main"
    some_patch = {"src/io_shop/purchase_ledger.py": "def record(account): ...\n"}
    some_service_source = {"src/io_shop/spend_summary.py": "def average(account): ...\n"}
    some_answer = CodeOutsideThePatch(
        uses=[CodeUse(name="month", path="src/io_shop/spend_summary.py", line=1,
                      function="average", does="returns it")],
        defined={"average": ["src/io_shop/spend_summary.py"]}
    )
    code = a_code_host_whose_source_is({
        **some_service_source, "src/target_app/scenarios.py": "def stage(): ...\n"
    })
    analyse = create_autospec(code_outside_the_patch, return_value=some_answer)

    Scenario() \
        .when(
            lambda: read_code_outside_the_patch(
                some_patch,
                some_ref,
                some_settings(source_paths="src/io_shop"),
                code=code,
                analyse=analyse
            )
        ) \
        .then(
            all_of(
                the_answer_was(some_answer),
                _the_source_was_read_at(code, some_ref),
                _the_analysis_was_given(analyse, some_service_source, some_patch)
            )
        )


@pytest.mark.unit
def test_the_code_outside_a_patch_that_could_not_be_read_is_refused_rather_than_empty() -> None:
    # No uses because none exist and no uses because nothing was read are
    # opposite facts, and the silent one tells Code-Fix nothing outside its
    # patch depends on what it changed.
    code = create_autospec(CodeHostReads, instance=True)
    code.source_at.side_effect = RepositoryUnreadable("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: read_code_outside_the_patch({}, DONT_CARE_REF, some_settings(),
                                                    code=code)
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


def _the_files_were_listed_at(code: Any, ref: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        asked = code.files_at.call_args.args[0]

        if asked != ref:
            raise AssertionError(f"Expected the files listed at [{ref}], got [{asked}].")

        return True

    return assertion


def _the_source_was_read_at(code: Any, ref: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        asked = code.source_at.call_args.args[0]

        if asked != ref:
            raise AssertionError(f"Expected the source read at [{ref}], got [{asked}].")

        return True

    return assertion


def _the_analysis_was_given(analyse: Any,
                            source: dict[str, str],
                            patch: dict[str, str]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        given = analyse.call_args.args

        if given != (source, patch):
            raise AssertionError(
                f"Expected the analysis given the service's own source {source} and "
                f"the patch {patch}, got {given}."
            )

        return True

    return assertion


def _exactly_these_files_matched(paths: list[str]) -> Assertion[list[str]]:
    """Which files the cause appears in, which is what the model acts on."""
    def assertion(hits: list[str]) -> bool:
        matched = sorted({hit.split(":", 1)[0] for hit in hits})

        if matched != sorted(paths):
            raise AssertionError(f"Expected hits in {sorted(paths)}, got {matched}.")

        return True

    return assertion


def _a_hit_quotes(text: str) -> Assertion[list[str]]:
    """The matching line travels, so a file can be judged without opening it."""
    def assertion(hits: list[str]) -> bool:
        if not any(text in hit for hit in hits):
            raise AssertionError(f"Expected a hit quoting [{text}], got {hits}.")

        return True

    return assertion


def _a_hit_reads(expected: str) -> Assertion[list[str]]:
    """Path, line number and line - the shape a developer already reads."""
    def assertion(hits: list[str]) -> bool:
        if expected not in hits:
            raise AssertionError(f"Expected a hit reading [{expected}], got {hits}.")

        return True

    return assertion


def _the_files_listed_are(paths: list[str]) -> Assertion[Any]:
    def assertion(listed: Any) -> bool:
        if list(listed) != paths:
            raise AssertionError(f"Expected the files {paths}, got {list(listed)}.")

        return True

    return assertion


def some_settings(source_paths: str = "") -> RepositoryReadSettings:
    """The slice this tier scopes source under.

    `source_paths` says which directories hold the service itself. Empty is the
    whole repository, which is right whenever the repository is nothing but the
    service.
    """
    return RepositoryReadSettings(service_source_paths=source_paths)


def a_code_host_listing(*paths: str) -> Any:
    """The code host's reads port, answering a listing with `paths`."""
    code = create_autospec(CodeHostReads, instance=True)
    code.files_at.return_value = list(paths)
    return code


def a_code_host_whose_source_is(files: dict[str, str]) -> Any:
    """The code host's reads port, answering the whole source with `files`.

    The seam this module actually has. Fetching an archive and unwrapping it
    belongs to the code host's adapter and is tested there; handing a real
    tarball to a search test would be exercising somebody else's unpacking to
    reach a subject that is only ever lines of text.
    """
    code = create_autospec(CodeHostReads, instance=True)
    code.source_at.return_value = files
    return code
