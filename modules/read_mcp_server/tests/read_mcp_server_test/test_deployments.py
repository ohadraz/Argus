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

from collections.abc import Callable
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import DeploymentChanges, DeploymentComparison
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.scenario import Scenario, attempting
from deployment_platform import DeploymentPlatformReads, DeploymentRecord
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

# Where the two revisions' lines of history part, for a deploy cut from before
# the revision that ran.
THE_MERGE_BASE = "a97029318f2d4c6b8e0a1c3e5f7092b4d6f8a0c2"

# What a deploy back to an earlier revision took away: a file the revision
# before had, removed.
THE_SCRAPE_CONFIGURATION = "deploy/scrape.yaml"
THE_SCRAPE_REMOVED = "@@ -1,2 +0,0 @@\n-scrape:\n-  port: metrics\n"


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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_three_times(),
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
                platform=an_application_deployed_once(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                platform=an_application_deployed_twice(),
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
                    platform=an_application_deployed_twice(),
                    compare=refused
                )
            )
        ) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
def test_a_deploy_ahead_of_the_one_before_it_is_said_as_it_always_was() -> None:
    # The ordinary deploy, and every recording's: nothing in what the model is
    # shown of it moves.
    compare = a_comparison_finding(
        a_changed_file(THE_CONFIGURATION_FILE, patch=THE_PORT_THAT_MOVED)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            ).said
        ) \
        .then(the_answer_was([
            f"Deployment of revision {THE_REVISION_DEPLOYED} to {SOME_SERVICE}, compared "
            f"against {THE_REVISION_DEPLOYED_BEFORE} - the revision deployed before it.",
            f"modified {THE_CONFIGURATION_FILE}",
            "  @@ -24,4 +24,4 @@ cache:",
            "     host: cache.io-shop.svc.cluster.local",
            "  -  port: 6379",
            "  +  port: 6380"
        ]))


@pytest.mark.unit
def test_a_deploy_back_to_an_earlier_revision_says_it_went_back_and_what_it_took_away(
) -> None:
    # Listed by what it brought, a deploy back to an ancestor brought nothing,
    # and read as a deploy that changed no file at all - which rules it out.
    compare = a_comparison_finding(
        relation="behind",
        taken_away=(a_changed_file(THE_SCRAPE_CONFIGURATION, patch=THE_SCRAPE_REMOVED,
                                   status="removed"),)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(f"It went back: {THE_REVISION_DEPLOYED} is in the history of "
                                 f"{THE_REVISION_DEPLOYED_BEFORE}"),
            _the_answer_mentions(f"removed {THE_SCRAPE_CONFIGURATION}"),
            _the_answer_mentions("-  port: metrics"),
            _the_answer_does_not_mention("changed no file")
        ))


@pytest.mark.unit
def test_a_deploy_from_another_line_says_what_it_brought_and_what_it_took_away() -> None:
    # Cut from before the revision that ran, it brings its own side and takes
    # the other's away - and said by its own side alone, it was half of what
    # changed. What it took away first: a file both sides changed is listed
    # twice, and its two patches compose only in the deploy's own order - back
    # to where the lines part, then on to what it deployed.
    compare = a_comparison_finding(
        a_changed_file(THE_SOURCE_FILE, patch=A_ONE_LINE_PATCH),
        relation="diverged",
        merge_base=THE_MERGE_BASE,
        taken_away=(a_changed_file(THE_CONFIGURATION_FILE, patch=THE_PORT_THAT_MOVED),)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_says_in_order(
                f"part at {THE_MERGE_BASE}. It took away what {THE_REVISION_DEPLOYED_BEFORE} "
                f"had changed since then:",
                f"modified {THE_CONFIGURATION_FILE}",
                f"and brought what {THE_REVISION_DEPLOYED} changed since then:",
                f"modified {THE_SOURCE_FILE}")
        ))


@pytest.mark.unit
def test_a_deploy_from_another_line_with_no_merge_base_named_says_the_lines_parted() -> None:
    # Where the comparison names none, the model is told the lines parted - and
    # never that they part at "None", a commit it would go looking for.
    compare = a_comparison_finding(
        a_changed_file(THE_SOURCE_FILE, patch=A_ONE_LINE_PATCH),
        relation="diverged",
        merge_base=None
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions("The two revisions are on lines of history that have parted."),
            _the_answer_does_not_mention("None")
        ))


@pytest.mark.unit
def test_a_copy_taken_away_says_why_it_has_no_diff() -> None:
    # Not the generic reason: the copy is text, and the comparison does carry a
    # diff for it - one against its source, which is not what removing it took
    # out. A wrong reason handed to a model is worse than none.
    compare = a_comparison_finding(
        relation="behind",
        taken_away=(ChangedFile(path=SOME_IMAGE, status="removed",
                                copied_from=THE_SOURCE_FILE),)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(all_of(
            _the_answer_mentions(f"it was a copy of {THE_SOURCE_FILE}"),
            _the_answer_does_not_mention("it is not text")
        ))


@pytest.mark.unit
def test_a_deploy_back_to_a_revision_holding_the_same_files_changed_no_file() -> None:
    # Neither side lists a file: the two revisions hold the same files, however
    # they stand in history.
    compare = a_comparison_finding(relation="behind")

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            )
        ) \
        .then(_the_answer_mentions("changed no file"))


@pytest.mark.unit
@pytest.mark.parametrize(("brought", "taken_away", "cut_off", "lists_every_file"), [
    (1, 0, False, True),
    (0, 0, False, True),
    (1, 0, True, False),
    (MOST_FILES_NAMED + 1, 0, False, False),
    (MOST_FILES_NAMED, 1, False, False)
], ids=["listed", "nothing", "cut-off", "more-than-named", "both-sides-past-named"])
def test_the_answer_says_whether_it_lists_every_file_the_two_revisions_differ_in(
        brought: int, taken_away: int, cut_off: bool, lists_every_file: bool) -> None:
    # Where it does, a file it does not name is as it was at the revision it
    # compares against - which the write-up says, and may only say there.
    compare = a_comparison_finding(
        *_numbered_files(brought),
        more_files_than_listed=cut_off,
        relation="diverged" if taken_away else "ahead",
        merge_base=THE_MERGE_BASE if taken_away else None,
        taken_away=_numbered_files(taken_away, from_number=brought)
    )

    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED,
                some_settings(),
                platform=an_application_deployed_twice(),
                compare=compare
            ).lists_every_file
        ) \
        .then(the_answer_was(lists_every_file))


@pytest.mark.unit
def test_a_deployment_with_nothing_before_it_lists_no_file() -> None:
    # No diff was read, so none is listed whole.
    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                THE_REVISION_DEPLOYED_BEFORE,
                some_settings(),
                platform=an_application_deployed_once(),
                compare=a_comparison_finding()
            ).lists_every_file
        ) \
        .then(the_answer_was(False))


@pytest.mark.unit
@pytest.mark.parametrize(("revision", "platform", "comparison"), [
    (THE_REVISION_DEPLOYED, lambda: an_application_deployed_twice(),
     DeploymentComparison.COMPARED),
    (THE_REVISION_DEPLOYED_BEFORE, lambda: an_application_deployed_once(),
     DeploymentComparison.NOTHING_BEFORE_IT),
    (A_FLAG_NAME, lambda: an_application_deployed_twice(),
     DeploymentComparison.NOT_DEPLOYED)
], ids=["compared", "nothing-before-it", "not-deployed"])
def test_the_answer_says_whether_a_comparison_was_made_and_why_not_where_none_was(
        revision: str, platform: Callable[[], Any], comparison: DeploymentComparison) -> None:
    # Only a comparison is a diff. The other two answers are facts about the
    # history, said to a model in its words - and every other reader says them
    # in its own, which it can do only knowing which answer this is.
    Scenario() \
        .when(
            lambda: what_a_deployment_changed(
                SOME_SERVICE,
                revision,
                some_settings(),
                platform=platform(),
                compare=a_comparison_finding()
            ).comparison
        ) \
        .then(the_answer_was(comparison))


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
                platform=an_application_deployed_twice(),
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
                         more_files_than_listed: bool = False,
                         relation: str = "ahead",
                         merge_base: str | None = None,
                         taken_away: tuple[ChangedFile, ...] = ()) -> Any:
    """The repository comparison, answering with the files named - and, for a
    deploy that is not ahead of the one before it, with what it took away.

    A double rather than the real reader: what belongs here is what this module
    does with a difference once it has one, and reading a repository is
    `repository_source`'s subject and tested there.
    """
    compare = create_autospec(_a_comparison_signature)
    compare.return_value = SourceDifference(
        base=THE_REVISION_DEPLOYED_BEFORE,
        head=THE_REVISION_DEPLOYED,
        files=tuple(files),
        more_files_than_listed=more_files_than_listed,
        relation=relation,
        merge_base=merge_base,
        taken_away=taken_away
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
    """The platform's history for one application, carrying the entries named."""
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.deployments_of.return_value = [
        DeploymentRecord(
            history_id=index,
            revision=revision,
            deployed_at=moment,
            repo_url=None,
            path=None,
            initiated_by=None
        )
        for index, (revision, moment) in enumerate(deployed, start=1)
    ]

    return platform


def _the_answer_mentions(wanted: str) -> Assertion[DeploymentChanges]:
    """Something a model has to be able to read in the answer."""
    def assertion(answered: DeploymentChanges) -> bool:
        if not any(wanted in line for line in answered.said):
            raise AssertionError(
                f"Expected the answer to mention [{wanted}], and it says "
                f"{answered.said}."
            )

        return True

    return assertion


def _the_answer_does_not_mention(unwanted: str) -> Assertion[DeploymentChanges]:
    """Something whose presence would mean the answer had lost its subject."""
    def assertion(answered: DeploymentChanges) -> bool:
        if any(unwanted in line for line in answered.said):
            raise AssertionError(
                f"Expected the answer not to mention [{unwanted}], and it says "
                f"{answered.said}."
            )

        return True

    return assertion


def _at_most_this_many_files_were_named(ceiling: int) -> Assertion[DeploymentChanges]:
    """How many of the changed paths reached the answer."""
    def assertion(answered: DeploymentChanges) -> bool:
        named = [
            line for line in answered.said
            if A_NUMBERED_MODULE.format(number="").rstrip(".py") in line
        ]

        if len(named) > ceiling:
            raise AssertionError(
                f"Expected at most [{ceiling}] files to be named, and "
                f"[{len(named)}] were."
            )

        return True

    return assertion


def _the_answer_says_in_order(*wanted: str) -> Assertion[DeploymentChanges]:
    """Each of these in some line of the answer, each after the one before it."""
    def assertion(answered: DeploymentChanges) -> bool:
        at = 0
        for one in wanted:
            found = next((place for place, line in enumerate(answered.said)
                          if place >= at and one in line), None)
            if found is None:
                raise AssertionError(
                    f"Expected the answer to say {list(wanted)} in that order, and "
                    f"[{one}] is not after what came before it in {answered.said}."
                )
            at = found + 1

        return True

    return assertion


def _numbered_files(count: int, from_number: int = 0) -> tuple[ChangedFile, ...]:
    """That many distinct files, where nothing about them but how many matters."""
    return tuple(a_changed_file(A_NUMBERED_MODULE.format(number=number), patch=None)
                 for number in range(from_number, from_number + count))


def _the_comparison_made_was(compare: Any,
                             base: str,
                             head: str) -> Assertion[DeploymentChanges]:
    """Which two revisions the repository was actually asked about."""
    def assertion(dont_care_answer: DeploymentChanges) -> bool:
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


def _no_comparison_was_made(compare: Any) -> Assertion[DeploymentChanges]:
    """That the repository was left alone.

    Asserted rather than assumed: there is nothing to compare in either of the
    cases this covers, and a call made anyway would be a request against a
    revision the history does not hold - answered by the API with a failure that
    reads as a repository problem.
    """
    def assertion(dont_care_answer: DeploymentChanges) -> bool:
        if compare.call_args_list:
            raise AssertionError(
                f"Expected no comparison to be asked for, and "
                f"{compare.call_args_list} was."
            )

        return True

    return assertion
