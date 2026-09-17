"""Which of a repository's files are the service, and which are around it.

A deployment points Argus at a repository and says which directories of it hold
the service. Everything else is scenery - a scenario harness, a deployment
chart, somebody's notebook - and reading it is worse than not reading it: the
demo repository ships the shop beside the rig that stages incidents against it,
and an agent that reads the rig is reading how its own incidents are made.

The rule lives in the kernel because two modules ask it and must agree. The
substring channel skips a file it will not match against, and the index skips
the same file rather than embedding it; the two answering differently would
make what a model can find depend on which tool it happened to reach for.

Prefix matching, because that is what somebody writing `src/io_shop` in an
environment file means. An empty setting admits everything rather than nothing:
a deployment that scoped nothing has a repository that is all service, and
answering it with no files at all would report an empty repository.
"""

from __future__ import annotations

import pytest
from argus_core.source_scope import belongs_to_the_service
from argus_testkit import Assertion, Scenario

SOME_SERVICE_DIRECTORY = "src/io_shop"
SOME_SERVICE_MODULE = "spend_summary.py"
SOME_SERVICE_PATH = f"{SOME_SERVICE_DIRECTORY}/{SOME_SERVICE_MODULE}"
SOME_HARNESS_PATH = "src/target_app/scenarios.py"
SOME_TESTS_DIRECTORY = "tests/io_shop"
SOME_TEST_PATH = f"{SOME_TESTS_DIRECTORY}/test_{SOME_SERVICE_MODULE}.py"


@pytest.mark.unit
def test_a_file_under_a_configured_directory_is_the_services_own() -> None:
    Scenario() \
        .given(the_service_lives_in := SOME_SERVICE_DIRECTORY) \
        .when(
            lambda: belongs_to_the_service(SOME_SERVICE_PATH, the_service_lives_in)
        ) \
        .then(_the_path_was_in_scope())


@pytest.mark.unit
def test_a_file_outside_every_configured_directory_is_not() -> None:
    # The one this rule exists for. The harness that stages incidents sits in
    # the same repository as the shop, and a fix agent reading it is reading
    # the answer sheet.
    Scenario() \
        .given(the_service_lives_in := SOME_SERVICE_DIRECTORY) \
        .when(
            lambda: belongs_to_the_service(SOME_HARNESS_PATH, the_service_lives_in)
        ) \
        .then(_the_path_was_out_of_scope())


@pytest.mark.unit
def test_a_file_under_the_second_of_several_directories_is_the_services_own() -> None:
    # A service and the tests that cover it are both the service, and they do
    # not live in one directory.
    Scenario() \
        .given(the_service_lives_in := f"{SOME_SERVICE_DIRECTORY},{SOME_TESTS_DIRECTORY}") \
        .when(
            lambda: belongs_to_the_service(SOME_TEST_PATH, the_service_lives_in)
        ) \
        .then(_the_path_was_in_scope())


@pytest.mark.unit
def test_space_around_a_configured_directory_is_not_part_of_it() -> None:
    # An environment file written by a person, who put a space after the comma
    # because that is how a list is written. A prefix of " tests/io_shop"
    # matches nothing, and the failure is silent: the directory is simply never
    # indexed and nobody is told why.
    Scenario() \
        .given(the_service_lives_in := f"{SOME_SERVICE_DIRECTORY}, {SOME_TESTS_DIRECTORY}") \
        .when(
            lambda: belongs_to_the_service(SOME_TEST_PATH, the_service_lives_in)
        ) \
        .then(_the_path_was_in_scope())


@pytest.mark.unit
def test_a_repository_that_scoped_nothing_is_all_service() -> None:
    # The ordinary deployment: Argus is pointed at a service's own repository,
    # and there is nothing in it that is not the service.
    Scenario() \
        .given(nothing_was_scoped := "") \
        .when(
            lambda: belongs_to_the_service(SOME_HARNESS_PATH, nothing_was_scoped)
        ) \
        .then(_the_path_was_in_scope())


@pytest.mark.unit
def test_a_setting_of_separators_alone_is_the_same_as_no_setting() -> None:
    # A list somebody emptied by deleting the entries and not the commas.
    # Reading it as a scope of three empty prefixes would admit every path by
    # accident rather than by decision - which is the same answer, and it is
    # worth knowing it is reached the same way.
    Scenario() \
        .given(the_entries_were_deleted := " , , ") \
        .when(
            lambda: belongs_to_the_service(
                SOME_HARNESS_PATH, the_entries_were_deleted
            )
        ) \
        .then(_the_path_was_in_scope())


def _the_path_was_in_scope() -> Assertion[bool]:
    return _path_in_scope(True)


def _the_path_was_out_of_scope() -> Assertion[bool]:
    return _path_in_scope(False)


def _path_in_scope(expected: bool) -> Assertion[bool]:
    def judged(in_scope: bool) -> str:
        return "the service's own" if in_scope else "out of scope"

    def answered(actual: bool) -> bool:
        if actual != expected:
            raise AssertionError(
                f"Expected the path to be judged {judged(expected)}, "
                f"and it was judged {judged(actual)}."
            )

        return True

    return answered
