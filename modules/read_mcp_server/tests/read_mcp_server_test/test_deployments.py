"""What one deployment changed, as the read tier answers it (spec §16).

The fifth retrieval channel, and the only one that answers about a change rather
than about the service. Two sources meet here: the deployment history says which
revision was running before the one being asked about, and the repository says
what differs between them. Both stay behind the port, so the caller names one
revision and learns what landed.

It exists for one distinction the rest of the tier cannot make. A bad deployment
and a broken configuration arrive the same way, move the same signals, and are
put right the same way - and what separates them is whether the commit that
landed touched source code or the values it shipped with. The deploy summary
cannot say: an application syncs from one directory for the life of the
application, so every deployment of the shop reports `deploy`, the ones that
rewrote source included.

Two bounds, and both are said in the answer rather than applied quietly. A
deployment can be a formatting sweep across a repository, and an answer returned
whole would spend a model's entire remaining context; an answer shortened in
silence would be read as the whole change, which is how a cause gets attributed
to the last file that happened to fit.

No scope. `github_source_paths` narrows what this tier searches and indexes to
the directories holding the service itself, which is right for reading code and
inverting here - the configuration a deployment ships lives outside the source
tree by definition, so a narrowed comparison would hide the one file that answers
the question, and hide it as an empty answer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.deployments import (
    MOST_FILES_NAMED,
    MOST_PATCH_LINES_ALL_TOLD,
    what_a_deployment_changed,
)
from read_mcp_server.repository import RepositoryReadSettings, RepositoryUnreadable
from repository_source import ChangedFile, SourceDifference

SOME_SERVICE = "io-shop"

THE_REVISION_DEPLOYED = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_DEPLOYED_BEFORE = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
A_REVISION_DEPLOYED_LONG_AGO = "70dbcfde2b549d110a3817d92d60b6dd9786e78b"

A_DEPLOY_MINUTE = "2026-08-20T11:05:00Z"
AN_EARLIER_DEPLOY_MINUTE = "2026-08-20T10:05:00Z"
THE_EARLIEST_DEPLOY_MINUTE = "2026-08-19T10:05:00Z"

# The two shapes the whole channel exists to tell apart. The first is outside
# `github_source_paths`, which is the trap: scoped, it disappears.
THE_CONFIGURATION_FILE = "deploy/values-production.yaml"
THE_SOURCE_FILE = "src/io_shop/spend_summary.py"

THE_PORT_THAT_MOVED = (
    "@@ -24,4 +24,4 @@ cache:\n"
    "   host: cache.io-shop.svc.cluster.local\n"
    "-  port: 6379\n"
    "+  port: 6380\n"
)

SOME_IMAGE = "src/target_app/assets/logo.png"

# What a feature flag's change is identified by. Not a revision, and no
# deployment has it - which is how the confusion arrives here.
A_FLAG_NAME = "monthly-spend-feature"

THE_CHANNEL_THAT_REPORTS_FLAG_CHANGES = "get_change_events"

# A template rather than a path: the tests that use it want many distinct files
# and care about nothing else about them.
A_NUMBERED_MODULE = "src/io_shop/module_{number}.py"

# One patch line per file, so that a test about the line budget is about the
# budget and not about how long a diff happens to be.
A_ONE_LINE_PATCH = "@@ -1 +1 @@\n"


@pytest.mark.unit
def test_what_a_deployment_changed_names_the_file_and_shows_the_change_in_it() -> None:
    # The patch is the point. A path alone leaves a reader inferring
    # configuration from a directory name, which is the inference that failed;
    # `port: 6379` becoming `port: 6380` is evidence instead of a cue.
    compare = a_comparison_finding(
        a_changed_file(THE_CONFIGURATION_FILE, patch=THE_PORT_THAT_MOVED)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(THE_CONFIGURATION_FILE),
            _the_answer_mentions("port: 6380")
        ))


@pytest.mark.unit
def test_the_deployment_is_compared_against_the_revision_deployed_before_it() -> None:
    # THE ONE THE WHOLE CHANNEL RESTS ON. Compared against anything else - the
    # commit's own parent, the oldest entry in some window - the answer describes
    # a change that was never deployed, and describes it in exactly the shape a
    # correct answer has. Nothing downstream could tell.
    compare = a_comparison_finding()

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(_the_comparison_made_was(
            compare,
            base=THE_REVISION_DEPLOYED_BEFORE,
            head=THE_REVISION_DEPLOYED
        ))


@pytest.mark.unit
def test_the_revision_before_is_the_one_immediately_before_and_not_the_earliest()\
        -> None:
    # A history of three, asked about the last: the base is the middle entry. An
    # implementation reaching for the first entry passes the test above and fails
    # here, and what it would report is every change of every deployment since.
    compare = a_comparison_finding()

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_three_times(),
                compare=compare
            )
        ) \
        .then(_the_comparison_made_was(
            compare,
            base=THE_REVISION_DEPLOYED_BEFORE,
            head=THE_REVISION_DEPLOYED
        ))


@pytest.mark.unit
def test_a_deployment_with_nothing_before_it_says_there_is_nothing_to_compare()\
        -> None:
    # A first deployment, and a real answer rather than a failure: there is no
    # earlier revision, so there is no diff, and that is a fact about the history
    # rather than about the attempt to read it.
    compare = a_comparison_finding()

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED_BEFORE,
                some_settings(),
                fetch=an_application_deployed_once(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions("no earlier deployment"),
            _no_comparison_was_made(compare)
        ))


@pytest.mark.unit
def test_a_revision_no_deployment_has_says_so_and_names_the_flag_channel() -> None:
    # How a flag's name arrives here: it is the `reference` of a change event,
    # exactly as a revision is, and a caller that read one channel's answer into
    # the other's argument has made a cheap mistake - cheap only if it is told.
    compare = a_comparison_finding()

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                A_FLAG_NAME,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(A_FLAG_NAME),
            _the_answer_mentions(THE_CHANNEL_THAT_REPORTS_FLAG_CHANGES),
            _no_comparison_was_made(compare)
        ))


@pytest.mark.unit
def test_a_deployment_that_changed_nothing_says_so() -> None:
    # A conclusion something acts on: this deployment did not cause this, so look
    # elsewhere. It has to be said, not left as an answer with no files in it.
    compare = a_comparison_finding()

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(_the_answer_mentions("changed no file"))


@pytest.mark.unit
def test_a_file_outside_the_service_s_own_source_is_reported_like_any_other() -> None:
    # THE ONE THAT INVERTS THE ANSWER IF IT IS EVER GOT WRONG. This tier narrows
    # what it searches and what it indexes to `github_source_paths`, and every
    # deployment's configuration is outside them. Narrowed here, the cache
    # scenario's entire diagnosis disappears - and it disappears as a deployment
    # that changed nothing, which is not a weaker answer than the truth but its
    # opposite.
    compare = a_comparison_finding(
        a_changed_file(THE_CONFIGURATION_FILE, patch=THE_PORT_THAT_MOVED)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                only_the_services_own_source(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(THE_CONFIGURATION_FILE),
            _the_answer_does_not_mention("changed no file")
        ))


@pytest.mark.unit
def test_a_file_with_no_diff_is_named_with_the_reason_it_has_none() -> None:
    # A file that is not text, or a diff the comparison judged too large, arrives
    # named and empty. Shown as a file with no change, it says the deployment
    # touched it and nothing happened - and a reader weighing whether any source
    # changed would count it as a no.
    compare = a_comparison_finding(a_changed_file(SOME_IMAGE, patch=None))

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(SOME_IMAGE),
            _the_answer_mentions("no diff")
        ))


@pytest.mark.unit
def test_a_comparison_that_listed_only_part_of_the_change_says_so() -> None:
    # The comparison itself reports a ceiling, and the answer has to carry that
    # forward. Left out, a deployment that rewrote a repository reads as one that
    # touched the handful of files the comparison happened to list.
    compare = a_comparison_finding(
        a_changed_file(THE_SOURCE_FILE, patch=A_ONE_LINE_PATCH),
        more_files_than_listed=True
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(_the_answer_mentions("not all of it"))


@pytest.mark.unit
def test_more_files_than_can_be_named_are_counted_rather_than_listed() -> None:
    # The first bound. Every changed file gets a line, which is cheap and is what
    # tells code from configuration - but a repository-wide sweep would make that
    # line the answer, so there is a ceiling on it and the ceiling is said.
    compare = a_comparison_finding(*(
        a_changed_file(A_NUMBERED_MODULE.format(number=number), patch=None)
        for number in range(MOST_FILES_NAMED + 1)
    ))

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions("more files, not named"),
            _at_most_this_many_files_were_named(MOST_FILES_NAMED)
        ))


@pytest.mark.unit
def test_changes_past_the_line_budget_are_named_without_being_shown() -> None:
    # The second bound, and the one that actually protects a turn. Names are
    # cheap and diffs are not, so the diffs stop and the names go on - a reader
    # still learns which files changed, which is the whole of the distinction
    # this channel exists for.
    compare = a_comparison_finding(*(
        a_changed_file(
            A_NUMBERED_MODULE.format(number=number), patch=A_ONE_LINE_PATCH
        )
        for number in range(MOST_PATCH_LINES_ALL_TOLD + 1)
    ))

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(_the_answer_mentions("not shown"))


@pytest.mark.unit
def test_a_repository_that_could_not_be_compared_raises() -> None:
    # Not an answer saying nothing changed. That answer rules the deployment out
    # as a cause, and a repository nobody could reach supports no such
    # conclusion - it must not arrive looking like one that does.
    refused = create_autospec(_a_comparison_signature)
    refused.side_effect = RepositoryUnreadable("no route to host")

    Scenario() \
        .when(
            attempting(
                lambda: what_a_deployment_changed(
                    SOME_SERVICE,
                    THE_REVISION_DEPLOYED,
                    some_settings(),
                    fetch=an_application_deployed_twice(),
                    compare=refused
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_the_answer_says_which_two_revisions_it_is_about() -> None:
    # What reads this is a model rather than the caller that asked. A diff that
    # does not say what it is a diff of is one the reader has to trust it was
    # handed correctly, and a rollback is addressed to one of the two.
    compare = a_comparison_finding(
        a_changed_file(THE_CONFIGURATION_FILE, patch=THE_PORT_THAT_MOVED)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                fetch=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(THE_REVISION_DEPLOYED),
            _the_answer_mentions(THE_REVISION_DEPLOYED_BEFORE)
        ))


def some_settings(source_paths: str = "") -> RepositoryReadSettings:
    """One repository and the credential that may only read it.

    The source paths are empty by default, which is this channel's own answer to
    the question: it compares a whole deployment, and the scope belongs to the
    channels that read code. One test sets them deliberately, to pin that setting
    them changes nothing here.
    """
    return RepositoryReadSettings(
        github_api_url="https://api.github.invalid",
        github_repository="dont-care/dont-care",
        github_read_token="ghp_dont-care-token",
        github_source_paths=source_paths
    )


def only_the_services_own_source() -> RepositoryReadSettings:
    """The scope as every deployment of the demo actually configures it."""
    return some_settings(source_paths="src/io_shop,tests/io_shop")


def a_changed_file(path: str,
                   patch: str | None,
                   status: str = "modified") -> ChangedFile:
    """One entry of a comparison, where only the path and the diff matter."""
    return ChangedFile(path=path, status=status, patch=patch)


def a_comparison_finding(*files: ChangedFile,
                         more_files_than_listed: bool = False) -> Any:
    """The repository comparison, answering with the files named.

    A double rather than the real reader: what belongs here is what this module
    does with a difference once it has one, and reading a repository is
    `repository_source`'s subject and tested there.
    """
    compare = create_autospec(_a_comparison_signature)
    compare.return_value = SourceDifference(
        base=THE_REVISION_DEPLOYED_BEFORE,
        head=THE_REVISION_DEPLOYED,
        files=tuple(files),
        more_files_than_listed=more_files_than_listed
    )

    return compare


def _a_comparison_signature(base: str,
                            head: str,
                            settings: Any) -> SourceDifference:
    """The shape this module asks a comparison in, for `create_autospec`.

    Specing against the real reader would spec against the wrong shape - it takes
    the repository's own settings slice and a transport, where this module asks
    about two revisions.
    """
    raise NotImplementedError


def an_application_deployed_once() -> Any:
    """A history with one entry: nothing was running before it."""
    return _a_history_of(
        (THE_REVISION_DEPLOYED_BEFORE, AN_EARLIER_DEPLOY_MINUTE)
    )


def an_application_deployed_twice() -> Any:
    """The ordinary case: one revision, and the one it replaced."""
    return _a_history_of(
        (THE_REVISION_DEPLOYED_BEFORE, AN_EARLIER_DEPLOY_MINUTE),
        (THE_REVISION_DEPLOYED, A_DEPLOY_MINUTE)
    )


def an_application_deployed_three_times() -> Any:
    """Three entries, so that "before" and "earliest" are different answers."""
    return _a_history_of(
        (A_REVISION_DEPLOYED_LONG_AGO, THE_EARLIEST_DEPLOY_MINUTE),
        (THE_REVISION_DEPLOYED_BEFORE, AN_EARLIER_DEPLOY_MINUTE),
        (THE_REVISION_DEPLOYED, A_DEPLOY_MINUTE)
    )


def _a_history_of(*deployed: tuple[str, str]) -> Any:
    """Argo CD's answer for one application, carrying the entries named."""
    argocd = create_autospec(_an_application_signature)
    argocd.return_value = {
        "status": {
            "history": [
                {"revision": revision, "deployedAt": moment}
                for revision, moment in deployed
            ]
        }
    }

    return argocd


def _an_application_signature(application: str) -> dict[str, Any]:
    """What asking the deployment history for one application looks like."""
    raise NotImplementedError


def _the_answer_mentions(wanted: str) -> Assertion[list[str]]:
    """Something a model has to be able to read in the answer."""
    def assertion(answered: list[str]) -> bool:
        if not any(wanted in line for line in answered):
            raise AssertionError(
                f"Expected the answer to mention [{wanted}], and it says "
                f"{answered}."
            )

        return True

    return assertion


def _the_answer_does_not_mention(unwanted: str) -> Assertion[list[str]]:
    """Something whose presence would mean the answer had lost its subject."""
    def assertion(answered: list[str]) -> bool:
        if any(unwanted in line for line in answered):
            raise AssertionError(
                f"Expected the answer not to mention [{unwanted}], and it says "
                f"{answered}."
            )

        return True

    return assertion


def _at_most_this_many_files_were_named(ceiling: int) -> Assertion[list[str]]:
    """How many of the changed paths reached the answer."""
    def assertion(answered: list[str]) -> bool:
        named = [
            line for line in answered
            if A_NUMBERED_MODULE.format(number="").rstrip(".py") in line
        ]

        if len(named) > ceiling:
            raise AssertionError(
                f"Expected at most [{ceiling}] files to be named, and "
                f"[{len(named)}] were."
            )

        return True

    return assertion


def _the_comparison_made_was(compare: Any,
                             base: str,
                             head: str) -> Assertion[list[str]]:
    """Which two revisions the repository was actually asked about."""
    def assertion(dont_care_answer: list[str]) -> bool:
        if not compare.call_args_list:
            raise AssertionError(
                f"Expected a comparison of [{base}] with [{head}], and no "
                f"comparison was asked for at all."
            )

        asked = compare.call_args_list[0]
        compared = (asked.args + tuple(asked.kwargs.values()))[:2]

        if compared != (base, head):
            raise AssertionError(
                f"Expected a comparison of [{base}] with [{head}], and "
                f"[{compared}] was asked for."
            )

        return True

    return assertion


def _no_comparison_was_made(compare: Any) -> Assertion[list[str]]:
    """That the repository was left alone.

    Asserted rather than assumed: there is nothing to compare in either of the
    cases this covers, and a call made anyway would be a request against a
    revision the history does not hold - answered by the API with a failure that
    reads as a repository problem.
    """
    def assertion(dont_care_answer: list[str]) -> bool:
        if compare.call_args_list:
            raise AssertionError(
                f"Expected no comparison to be asked for, and "
                f"{compare.call_args_list} was."
            )

        return True

    return assertion
