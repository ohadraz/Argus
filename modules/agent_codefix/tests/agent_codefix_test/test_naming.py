"""The files the investigation's evidence names, found in the repository.

Greedy on purpose, with the listing as the safety net: a name the evidence
spells in any of the ways its log lines and prose spell one - a path with a
line, a bare filename, a log's path inside the container, a dotted module, a
stem - is looked for, and only what the repository holds is listed. What is
said to be missing is narrower: only a name shaped like a file the repository
could hold, because "not in the repository" said of `account.total_cents` is a
stale-path warning about an attribute.
"""

from __future__ import annotations

import pytest
from agent_codefix.naming import FilesNamed, files_named_in
from argus_testkit import Scenario, the_answer_was

SOME_PATH = "src/io_shop/spend_summary.py"
SOME_OTHER_PATH = "src/io_shop/purchase_ledger.py"
SOME_CONFIG = "deploy/values-production.yaml"
SOME_DATA = "src/io_shop/fixtures.json"

SOME_LISTING = [SOME_PATH, SOME_OTHER_PATH, SOME_CONFIG, SOME_DATA,
                "tests/io_shop/test_spend_summary.py"]

NOTHING_NAMED = FilesNamed(held=[], absent=[])


@pytest.mark.unit
@pytest.mark.parametrize("claim", [
    f"division by zero at {SOME_PATH}:47",
    f"the divisor at {SOME_PATH}:44-46 is never checked",
    f"division by zero at /app/{SOME_PATH}:47",
    "modified spend_summary.py: the guard was removed",
    "io_shop.spend_summary.average_spend_per_item_this_month divides by the month",
    "spend_summary divides by an empty month",
    "division by zero at /usr/local/lib/python3.12/site-packages/io_shop/spend_summary.py:47"
], ids=["path-and-line", "path-and-line-range", "path-inside-the-container",
        "bare-filename", "dotted-module", "stem", "path-in-an-installed-package"])
def test_a_file_the_evidence_names_is_listed_by_its_path_in_the_repository(
        claim: str) -> None:
    Scenario() \
        .when(
            lambda: files_named_in([claim], SOME_LISTING)
        ) \
        .then(
            the_answer_was(FilesNamed(held=[SOME_PATH], absent=[]))
        )


@pytest.mark.unit
def test_a_path_to_a_file_with_no_extension_is_listed_by_its_path_in_the_repository() -> None:
    some_dockerfile = "images/postgres-faketime/Dockerfile"

    Scenario() \
        .when(
            lambda: files_named_in(["built from postgres-faketime/Dockerfile"],
                                   [*SOME_LISTING, some_dockerfile])
        ) \
        .then(
            the_answer_was(FilesNamed(held=[some_dockerfile], absent=[]))
        )


@pytest.mark.unit
def test_a_file_the_repository_does_not_hold_is_said_to_be_missing() -> None:
    # Dropped, a stale path is invisible - which is the opposite of the point.
    some_missing_path = "src/io_shop/spend_report.py"

    Scenario() \
        .when(
            lambda: files_named_in([f"division by zero at {some_missing_path}:12"],
                                   SOME_LISTING)
        ) \
        .then(
            the_answer_was(FilesNamed(held=[], absent=[some_missing_path]))
        )


@pytest.mark.unit
def test_a_file_sharing_only_its_name_with_one_the_repository_holds_is_not_that_file() -> None:
    # Two segments in common are a module's import path; one is a filename
    # every other package has too.
    some_other_packages_file = "/usr/local/lib/python3.12/site-packages/requests/models.py"

    Scenario() \
        .when(
            lambda: files_named_in([f"raised at {some_other_packages_file}:12"],
                                   [*SOME_LISTING, "src/io_shop/models.py"])
        ) \
        .then(
            the_answer_was(FilesNamed(held=[], absent=[some_other_packages_file]))
        )


@pytest.mark.unit
@pytest.mark.parametrize("claim", [
    "slow upstream call - pricing.io-internal.svc took 1500ms",
    "p50/p95/p99 jump while request_volume stays flat",
    "slow upstream call for /v1/shoppers/shopper-35697-6-0/basket-total",
    "return account.total_cents // len(account.purchases)",
    "the account page request failed",
    "body = response.json() raised"
], ids=["host", "metric-columns", "url-path", "attribute", "plain-words", "call"])
def test_a_name_that_is_no_file_is_neither_listed_nor_said_missing(claim: str) -> None:
    # A host ends in no extension the repository's files carry, a run of
    # slashes is not a path for having them, an attribute is not a module, and
    # a word is a file only where a file is called that. A call is never a
    # file, whatever extension its name ends in.
    Scenario() \
        .when(
            lambda: files_named_in([claim], SOME_LISTING)
        ) \
        .then(
            the_answer_was(NOTHING_NAMED)
        )


@pytest.mark.unit
def test_a_stem_several_files_share_lists_every_one() -> None:
    # Nothing in the word says which was meant.
    some_namesake = "src/admin/spend_summary.py"

    Scenario() \
        .when(
            lambda: files_named_in(["spend_summary divides by an empty month"],
                                   [*SOME_LISTING, some_namesake])
        ) \
        .then(
            the_answer_was(FilesNamed(held=[SOME_PATH, some_namesake], absent=[]))
        )


@pytest.mark.unit
def test_files_are_listed_once_each_in_the_order_the_evidence_first_names_them() -> None:
    Scenario() \
        .when(
            lambda: files_named_in([f"modified {SOME_CONFIG} and {SOME_PATH}",
                                    f"division by zero at {SOME_CONFIG}:3",
                                    f"division by zero at {SOME_PATH}:47"],
                                   SOME_LISTING)
        ) \
        .then(
            the_answer_was(FilesNamed(held=[SOME_CONFIG, SOME_PATH], absent=[]))
        )
