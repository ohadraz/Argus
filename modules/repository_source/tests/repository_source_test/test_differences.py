"""What one deployment changed, read as the difference between two commits.

The evidence that tells a bad deployment from a broken configuration, and the
only evidence that does. Both arrive as a deployment, both move the same signals,
and both are put right by returning the deployment - what separates them is
whether the commit that landed touched source code or the values it shipped with,
which is a fact about a diff and about nothing else Argus retrieves.

Beside `comparing.py`'s question rather than inside it, because the two want
opposite things at the same ceiling. A catch-up pass handed three hundred files
must reconsider the repository entire, so it is told nothing can be said; an
investigation handed three hundred files has learned something worth acting on -
this deployment changed a great deal, source included - and being told nothing
would be worse than being told the first three hundred.

Every path, with no scope applied. The directories holding the service's own
source are what a search is narrowed to and are the wrong thing here: the
configuration a deployment ships lives outside the source tree by definition, so
a narrowed comparison hides the one file that answers the question - and hides it
as an empty answer, which reads as a deployment that changed nothing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from repository_source import ChangedFile, RepositoryUnreadable, SourceDifference
from repository_source.comparing import MOST_FILES_A_COMPARISON_LISTS
from repository_source.differences import the_difference_between

from repository_source_test.framework.settings import some_settings

THE_REVISION_DEPLOYED_BEFORE = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
THE_REVISION_DEPLOYED = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"

DONT_CARE_BASE = THE_REVISION_DEPLOYED_BEFORE
DONT_CARE_HEAD = THE_REVISION_DEPLOYED

# The two shapes the whole channel exists to tell apart: a value that moved in a
# file the deployment carried, and source code that was rewritten.
THE_CONFIGURATION_FILE = "deploy/values-production.yaml"
THE_SOURCE_FILE = "src/io_shop/spend_summary.py"

THE_PORT_THAT_MOVED = (
    "@@ -24,4 +24,4 @@ cache:\n"
    "   host: cache.io-shop.svc.cluster.local\n"
    "-  port: 6379\n"
    "+  port: 6380\n"
)

SOME_PATCH = "@@ -1,3 +1,4 @@\n-    return cached\n+    return recomputed\n"

SOME_IMAGE = "src/target_app/assets/logo.png"

SOME_FILE_RENAMED_FROM = "src/io_shop/summaries.py"
SOME_FILE_RENAMED_TO = "src/io_shop/spending.py"

# A template rather than a path: the one test that uses it wants three hundred
# distinct files and cares about nothing else about them.
A_NUMBERED_MODULE = "src/io_shop/module_{number}.py"


@pytest.mark.unit
def test_a_changed_file_comes_back_with_its_path_and_what_changed_in_it() -> None:
    # The patch is the whole point. A path alone leaves a reader inferring
    # configuration from a directory name, which is the inference that fails;
    # `port: 6379` becoming `port: 6380` is evidence instead of a cue.
    compared = a_comparison_of({
        "filename": THE_CONFIGURATION_FILE,
        "status": "modified",
        "patch": THE_PORT_THAT_MOVED
    })

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(all_of(
            _the_files_that_changed_are([THE_CONFIGURATION_FILE]),
            _the_change_to(THE_CONFIGURATION_FILE, was=THE_PORT_THAT_MOVED),
            _the_status_of(THE_CONFIGURATION_FILE, was="modified")
        ))


@pytest.mark.unit
def test_a_file_outside_the_service_s_own_source_is_reported_like_any_other() -> None:
    # THE ONE THAT INVERTS THE ANSWER IF IT IS EVER GOT WRONG. The read tier
    # narrows what it searches and what it indexes to the directories holding
    # the service itself, and every deployment's configuration is outside them.
    # Narrowed here, the cache scenario's entire diagnosis disappears - and it
    # disappears as an empty comparison, which is not a weaker answer than the
    # truth but its opposite: the deployment changed nothing, so rule it out.
    compared = a_comparison_of({
        "filename": THE_CONFIGURATION_FILE,
        "status": "modified",
        "patch": THE_PORT_THAT_MOVED
    })

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_files_that_changed_are([THE_CONFIGURATION_FILE]))


@pytest.mark.unit
def test_a_file_the_api_gave_no_patch_for_says_so_rather_than_reading_as_unchanged()\
        -> None:
    # A binary file, or a diff the API judged too large, arrives with every
    # other field and no `patch` at all. Read as an empty change, it says the
    # file was touched and nothing happened to it - and a reader weighing "did
    # any source change" would count it as a no.
    compared = a_comparison_of({"filename": SOME_IMAGE, "status": "modified"})

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(all_of(
            _the_files_that_changed_are([SOME_IMAGE]),
            _the_change_to(SOME_IMAGE, was=None)
        ))


@pytest.mark.unit
def test_a_renamed_file_names_where_it_was_as_well_as_where_it_is() -> None:
    # A rename is a deletion and an addition wearing one entry. Named only by
    # where the file went, a reader cannot tell a file that moved from one that
    # appeared - and the two say different things about what a deployment did.
    compared = a_comparison_of({
        "filename": SOME_FILE_RENAMED_TO,
        "status": "renamed",
        "previous_filename": SOME_FILE_RENAMED_FROM,
        "patch": SOME_PATCH
    })

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(all_of(
            _the_files_that_changed_are([SOME_FILE_RENAMED_TO]),
            _the_file_was_previously_at(SOME_FILE_RENAMED_TO, SOME_FILE_RENAMED_FROM)
        ))


@pytest.mark.unit
def test_two_commits_with_nothing_between_them_differ_in_no_file() -> None:
    # A real answer, and one an investigation acts on: this deployment changed
    # nothing, so it did not cause this. Distinct from the comparison that could
    # not be made, which is two tests below and means the opposite.
    compared = a_comparison_of()

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(all_of(
            _the_files_that_changed_are([]),
            _every_file_was_listed()
        ))


@pytest.mark.unit
def test_a_comparison_at_the_api_s_ceiling_says_there_were_more_than_it_listed()\
        -> None:
    # Where this parts company with `paths_changed_between`, deliberately. That
    # one answers "I cannot say", because a pass that indexed three hundred of a
    # thousand files would record the index as current over passages nobody
    # updated. An investigation has no such trap: three hundred files is itself
    # the finding - this deployment changed a great deal - and refusing to say so
    # would throw away the answer to keep a purity nothing here needs.
    compared = a_comparison_of(*(
        {
            "filename": A_NUMBERED_MODULE.format(number=number),
            "status": "modified",
            "patch": SOME_PATCH
        }
        for number in range(MOST_FILES_A_COMPARISON_LISTS)
    ))

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(all_of(
            _there_were_more_files_than_were_listed(),
            _this_many_files_were_listed(MOST_FILES_A_COMPARISON_LISTS)
        ))


@pytest.mark.unit
def test_a_comparison_within_the_ceiling_says_every_file_was_listed() -> None:
    # The other side of the flag, and the reason it is a flag rather than a
    # count: a reader has to be able to tell a complete answer from a cut-off
    # one, and a short list is what both look like.
    compared = a_comparison_of({
        "filename": THE_SOURCE_FILE,
        "status": "modified",
        "patch": SOME_PATCH
    })

    Scenario() \
        .when(
            lambda: the_difference_between(
                DONT_CARE_BASE,
                DONT_CARE_HEAD,
                some_settings(),
                get=compared
            )
        ) \
        .then(_every_file_was_listed())


@pytest.mark.unit
def test_a_comparison_that_could_not_be_made_raises() -> None:
    # Not an empty difference. "This deployment changed nothing" rules the
    # deployment out as a cause, and a repository nobody could reach supports no
    # such conclusion - it must not arrive looking like one that does.
    refused = create_autospec(httpx2.get)
    refused.side_effect = httpx2.ConnectError("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: the_difference_between(
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
    # Ordered, and it matters: reversed, the difference describes putting the
    # deployment back rather than making it - and a port that moved reads as a
    # port that was fixed.
    compared = a_comparison_of()

    Scenario() \
        .when(
            lambda: the_difference_between(
                THE_REVISION_DEPLOYED_BEFORE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_request_ended_with(
            compared,
            f"/compare/{THE_REVISION_DEPLOYED_BEFORE}...{THE_REVISION_DEPLOYED}"
        ))


@pytest.mark.unit
def test_the_difference_names_the_two_revisions_it_was_taken_between() -> None:
    # Carried in the answer rather than left with whoever asked. What a model
    # reads is this difference, and a diff that does not say what it is a diff
    # of is one the model has to trust it was handed correctly.
    compared = a_comparison_of()

    Scenario() \
        .when(
            lambda: the_difference_between(
                THE_REVISION_DEPLOYED_BEFORE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                get=compared
            )
        ) \
        .then(_the_revisions_compared_were(
            base=THE_REVISION_DEPLOYED_BEFORE, head=THE_REVISION_DEPLOYED
        ))


def _the_files_that_changed_are(paths: list[str]) -> Assertion[SourceDifference]:
    """Which files the deployment touched, and no others."""
    def assertion(difference: SourceDifference) -> bool:
        changed = sorted(changed_file.path for changed_file in difference.files)

        if changed != sorted(paths):
            raise AssertionError(
                f"Expected the deployment to have changed {sorted(paths)}, and it "
                f"reports {changed}."
            )

        return True

    return assertion


def _the_change_to(path: str, was: str | None) -> Assertion[SourceDifference]:
    """What happened inside one file, as the difference carries it."""
    def assertion(difference: SourceDifference) -> bool:
        carried = _the_entry_for(path, difference).patch

        if carried != was:
            raise AssertionError(
                f"Expected the change to [{path}] to be [{was}], and it is "
                f"[{carried}]."
            )

        return True

    return assertion


def _the_status_of(path: str, was: str) -> Assertion[SourceDifference]:
    """Whether the file was added, changed, removed or moved."""
    def assertion(difference: SourceDifference) -> bool:
        reported = _the_entry_for(path, difference).status

        if reported != was:
            raise AssertionError(
                f"Expected [{path}] to be reported as [{was}], and it is "
                f"reported as [{reported}]."
            )

        return True

    return assertion


def _the_file_was_previously_at(path: str,
                                previous_path: str) -> Assertion[SourceDifference]:
    """Where a file that moved used to be."""
    def assertion(difference: SourceDifference) -> bool:
        was_at = _the_entry_for(path, difference).previous_path

        if was_at != previous_path:
            raise AssertionError(
                f"Expected [{path}] to say it was previously at "
                f"[{previous_path}], and it says [{was_at}]."
            )

        return True

    return assertion


def _there_were_more_files_than_were_listed() -> Assertion[SourceDifference]:
    """The answer saying it is the first of the change rather than all of it."""
    def assertion(difference: SourceDifference) -> bool:
        if not difference.more_files_than_listed:
            raise AssertionError(
                "Expected the difference to report that more files changed than "
                "it listed, and it reports itself as the whole change - so a "
                "deployment that rewrote a repository reads as one that touched "
                "the handful of files that happened to fit."
            )

        return True

    return assertion


def _every_file_was_listed() -> Assertion[SourceDifference]:
    """The answer saying it is the whole change."""
    def assertion(difference: SourceDifference) -> bool:
        if difference.more_files_than_listed:
            raise AssertionError(
                "Expected the difference to report itself as the whole change, "
                "and it reports that more files changed than it listed."
            )

        return True

    return assertion


def _this_many_files_were_listed(expected: int) -> Assertion[SourceDifference]:
    """How many entries survived, where the paths themselves do not matter."""
    def assertion(difference: SourceDifference) -> bool:
        if len(difference.files) != expected:
            raise AssertionError(
                f"Expected [{expected}] changed files, got "
                f"[{len(difference.files)}]."
            )

        return True

    return assertion


def _the_revisions_compared_were(base: str,
                                 head: str) -> Assertion[SourceDifference]:
    """What the difference says it is a difference of."""
    def assertion(difference: SourceDifference) -> bool:
        if (difference.base, difference.head) != (base, head):
            raise AssertionError(
                f"Expected a difference between [{base}] and [{head}], and it "
                f"reports one between [{difference.base}] and "
                f"[{difference.head}]."
            )

        return True

    return assertion


def _the_request_ended_with(compared: Any,
                            path: str) -> Assertion[SourceDifference]:
    def assertion(dont_care_difference: SourceDifference) -> bool:
        addressed = [made.args[0] for made in compared.call_args_list]

        if not any(url.endswith(path) for url in addressed):
            raise AssertionError(
                f"Expected a request ending [{path}], got {addressed}."
            )

        return True

    return assertion


def _the_entry_for(path: str, difference: SourceDifference) -> ChangedFile:
    """The one entry a per-file assertion is about.

    Raises rather than returning nothing for a path that is not in the
    difference: the assertion calling this has already been told which files
    changed by the assertion beside it, so a missing entry here is a test whose
    two halves disagree, and saying so beats a comparison against `None`.
    """
    for changed_file in difference.files:
        if changed_file.path == path:
            return changed_file

    raise AssertionError(
        f"Expected the difference to hold an entry for [{path}], and it holds "
        f"entries for "
        f"{[changed_file.path for changed_file in difference.files]}."
    )


def a_comparison_of(*files: dict[str, str]) -> Any:
    """GitHub's answer for two commits, carrying the entries it lists."""
    compared = create_autospec(httpx2.get)
    compared.return_value = httpx2.Response(
        status_code=200,
        json={"files": list(files)},
        request=httpx2.Request("GET", "http://github.invalid/")
    )

    return compared
