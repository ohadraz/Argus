"""The code host's ports, as every adapter of them answers.

What the ports promise, asked of each adapter over one seed: the GitHub
adapters against `github_double` served in-process (`framework.github_in_process`),
and the in-memory double (`code_host_double`). A promise one of them keeps and
the other does not fails here, so the double cannot drift from the ports, and
the ports name nothing only GitHub's wire could answer.

The promises and nothing beyond them. A patch is compared by the lines it takes
out and the lines it puts in, never as text: how a hunk is headed is GitHub's,
and the wire suites' (`github/test_differences.py`). Every seed's change has one
alignment - a line replaced, a line appended - so the lines are the same
whichever diff wrote them. Two commits with no common ancestor are not asked
about: `github_double` answers them for the stacks alone.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from argus_testkit import (
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    dont_care_sleep,
    the_answer_was,
)
from code_host import (
    BranchNotWritten,
    ChangedFile,
    CodeHostReads,
    CodeHostWrites,
    PullRequestNotOpened,
    Relation,
    RepositoryUnreadable,
    SourceDifference,
)
from code_host.github import GitHub, GitHubReads
from code_host_double import HeldCommit, InMemoryCodeHost, RepositoryState

from code_host_test.framework.github_in_process import THE_DOUBLES_ADDRESS, GitHubInProcess
from code_host_test.framework.settings import some_repository_settings, some_settings

SOME_REPOSITORY = "some-owner/some-repository"


def _a_sha(of: str) -> str:
    """Forty hex characters, as a commit is named - here rather than among the
    helpers below, since the seed is built from it."""
    return hashlib.sha1(of.encode()).hexdigest()


# Two files, one a directory down, so a listing that named a directory as a
# file would be caught.
A_FILE = "src/some_service/some_module.py"
ANOTHER_FILE = "README.md"
A_FILE_ADDED = "src/some_service/another_module.py"
NO_SUCH_PATH = "src/some_service/no_such_module.py"
THEIR_DIRECTORY = "src/some_service"

AS_FIRST_WRITTEN = "one\ntwo\nthree\n"
WITH_A_LINE_REPLACED = "one\nTWO\nthree\n"
ANOTHER_AS_FIRST_WRITTEN = "alpha\nbeta\n"
WITH_A_LINE_APPENDED = "alpha\nbeta\ngamma\n"
AS_ADDED = "four\nfive\n"

# The first commit, one made on it, and one made on it beside that one: so a
# head can stand ahead of, level with, behind or apart from its base.
THE_FIRST_COMMIT = _a_sha("the first commit")
A_COMMIT_ON_IT = _a_sha("a commit made on the first")
A_COMMIT_BESIDE_IT = _a_sha("another commit made on the first")
NO_SUCH_COMMIT = _a_sha("a commit nobody made")

THE_FIRST_FILES = {A_FILE: AS_FIRST_WRITTEN, ANOTHER_FILE: ANOTHER_AS_FIRST_WRITTEN}
THE_FILES_ON_IT = {A_FILE: WITH_A_LINE_REPLACED, ANOTHER_FILE: ANOTHER_AS_FIRST_WRITTEN,
                   A_FILE_ADDED: AS_ADDED}
THE_FILES_BESIDE_IT = {A_FILE: AS_FIRST_WRITTEN, ANOTHER_FILE: WITH_A_LINE_APPENDED}

# Never `main`: the double's `main` holds the shop's fixture whatever the seed.
SOME_BRANCH = "some-branch"
SOME_BASE_BRANCH = "some-base-branch"
A_NEW_BRANCH = "argus/some-fix"
NO_SUCH_BRANCH = "no-such-branch"

THE_SEED = RepositoryState(
    commits=(
        HeldCommit(sha=THE_FIRST_COMMIT, files=tuple(THE_FIRST_FILES.items())),
        HeldCommit(sha=A_COMMIT_ON_IT, files=tuple(THE_FILES_ON_IT.items()),
                   parents=(THE_FIRST_COMMIT,)),
        HeldCommit(sha=A_COMMIT_BESIDE_IT, files=tuple(THE_FILES_BESIDE_IT.items()),
                   parents=(THE_FIRST_COMMIT,))
    ),
    branches=((SOME_BRANCH, A_COMMIT_ON_IT), (SOME_BASE_BRANCH, THE_FIRST_COMMIT))
)

# A fix: one file rewritten whole, and a test the base did not have.
A_FIX = {A_FILE: "one\nfixed\nthree\n", "tests/test_some_module.py": "def test_it() -> None: ...\n"}
SOME_MESSAGE = "Fix some module"
SOME_TITLE = "Fix some module"
SOME_BODY = "What was wrong, and how this puts it right."

# A repository on a host whose pages nothing knows.
A_REPOSITORY_ON_AN_UNKNOWN_HOST = "https://code.example.invalid/some-owner/some-repository.git"

# One file of a difference as a reader is handed it: where it is, what
# happened to it, where it came from on a rename or a copy, and the lines its
# patch takes out and puts in.
type _Read = tuple[str, str, str | None, str | None, tuple[str, ...], tuple[str, ...]]


@dataclass(frozen=True)
class _Host:
    """A host as a case asks it: both ports, and what it was asked to propose -
    each as head, base, title, body and whether a draft."""

    reads: CodeHostReads
    writes: CodeHostWrites
    proposed: Callable[[], list[tuple[str, str, str, str, bool]]]


class _StandsUp(Protocol):
    def __call__(self, state: RepositoryState, *, unreachable: bool = ...) -> _Host:
        ...


def _in_memory(state: RepositoryState, *, unreachable: bool = False) -> _Host:
    host = InMemoryCodeHost(state, repository=SOME_REPOSITORY, unreachable=unreachable)

    return _Host(reads=host, writes=host, proposed=lambda: [
        (each.head, each.base, each.title, each.body, each.draft) for each in host.proposed
    ])


def _github(state: RepositoryState, *, unreachable: bool = False) -> _Host:
    github = GitHubInProcess(unreachable=unreachable).holding(state, SOME_REPOSITORY)

    return _Host(
        reads=GitHubReads(some_settings(api_url=THE_DOUBLES_ADDRESS, repository=SOME_REPOSITORY),
                          get=github.get),
        writes=GitHub(some_repository_settings(api_url=THE_DOUBLES_ADDRESS,
                                               repository=SOME_REPOSITORY),
                      get=github.get, post=github.post, sleep=dont_care_sleep),
        proposed=github.proposed
    )


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_github, id="github")
])


@pytest.fixture(autouse=True)
def _the_double_put_back() -> Iterator[None]:
    """`github_double` holds one repository for the whole process: put back
    after every case, so none finds another's branches."""
    yield
    GitHubInProcess().put_back()


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_repository_is_the_one_the_host_holds(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.repository) \
        .then(the_answer_was(SOME_REPOSITORY))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_files_at_a_commit_are_every_file_it_holds_and_no_directory(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: sorted(host.reads.files_at(A_COMMIT_ON_IT))) \
        .then(the_answer_was(sorted(THE_FILES_ON_IT)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_file_at_a_commit_is_what_it_says_there(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.file_at(A_FILE, A_COMMIT_ON_IT)) \
        .then(the_answer_was(WITH_A_LINE_REPLACED))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("path", [
    pytest.param(A_FILE_ADDED, id="a file a later commit added"),
    pytest.param(NO_SUCH_PATH, id="a file no commit holds"),
    pytest.param(THEIR_DIRECTORY, id="a directory")
])
def test_a_path_that_is_no_file_at_a_commit_is_refused(stand_up: _StandsUp, path: str) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(attempting(lambda: host.reads.file_at(path, THE_FIRST_COMMIT))) \
        .then(an_error_was_raised(RepositoryUnreadable))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_source_at_a_commit_is_every_file_and_what_each_says(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.source_at(A_COMMIT_ON_IT)) \
        .then(the_answer_was(THE_FILES_ON_IT))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_branch_s_head_is_the_commit_it_points_at(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.head_of(SOME_BRANCH)) \
        .then(the_answer_was(A_COMMIT_ON_IT))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("revision", "contained"), [
    pytest.param(A_COMMIT_ON_IT, True, id="the commit it points at"),
    pytest.param(THE_FIRST_COMMIT, True, id="a commit in its history"),
    pytest.param(A_COMMIT_BESIDE_IT, False, id="a commit on another line")
])
def test_a_branch_contains_its_head_and_every_commit_in_its_history(
    stand_up: _StandsUp, revision: str, contained: bool
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.contains(SOME_BRANCH, revision)) \
        .then(the_answer_was(contained))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("ask", [
    pytest.param(lambda reads: reads.head_of(NO_SUCH_BRANCH), id="the head of no branch"),
    pytest.param(lambda reads: reads.contains(NO_SUCH_BRANCH, THE_FIRST_COMMIT),
                 id="whether no branch contains a commit"),
    pytest.param(lambda reads: reads.contains(SOME_BRANCH, NO_SUCH_COMMIT),
                 id="whether a branch contains no commit"),
    pytest.param(lambda reads: reads.files_at(NO_SUCH_COMMIT), id="the files at no commit"),
    pytest.param(lambda reads: reads.file_at(A_FILE, NO_SUCH_COMMIT), id="a file at no commit"),
    pytest.param(lambda reads: reads.source_at(NO_SUCH_COMMIT), id="the source at no commit"),
    pytest.param(lambda reads: reads.difference_between(THE_FIRST_COMMIT, NO_SUCH_COMMIT),
                 id="the difference from a commit to none"),
    pytest.param(lambda reads: reads.paths_changed_between(THE_FIRST_COMMIT, NO_SUCH_COMMIT),
                 id="the paths changed from a commit to none")
])
def test_a_branch_or_commit_the_host_does_not_hold_is_refused(
    stand_up: _StandsUp, ask: Callable[[CodeHostReads], Any]
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(attempting(lambda: ask(host.reads))) \
        .then(an_error_was_raised(RepositoryUnreadable))


# What each file of a difference is, read in the direction its list reads.
_A_FILE_REPLACED = (A_FILE, "modified", None, None, ("two",), ("TWO",))
_A_FILE_PUT_BACK = (A_FILE, "modified", None, None, ("TWO",), ("two",))
_THE_NEW_FILE_ARRIVING = (A_FILE_ADDED, "added", None, None, (), ("four", "five"))
_THE_NEW_FILE_TAKEN_AWAY = (A_FILE_ADDED, "removed", None, None, ("four", "five"), ())
_ANOTHER_FILE_APPENDED = (ANOTHER_FILE, "modified", None, None, (), ("gamma",))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("base", "head", "relation", "merge_base", "files", "taken_away"), [
    pytest.param(THE_FIRST_COMMIT, A_COMMIT_ON_IT, Relation.AHEAD, THE_FIRST_COMMIT,
                 [_A_FILE_REPLACED, _THE_NEW_FILE_ARRIVING], [], id="ahead"),
    pytest.param(A_COMMIT_ON_IT, A_COMMIT_ON_IT, Relation.IDENTICAL, A_COMMIT_ON_IT,
                 [], [], id="identical"),
    pytest.param(A_COMMIT_ON_IT, THE_FIRST_COMMIT, Relation.BEHIND, THE_FIRST_COMMIT,
                 [], [_A_FILE_PUT_BACK, _THE_NEW_FILE_TAKEN_AWAY], id="behind"),
    pytest.param(A_COMMIT_ON_IT, A_COMMIT_BESIDE_IT, Relation.DIVERGED, THE_FIRST_COMMIT,
                 [_ANOTHER_FILE_APPENDED], [_A_FILE_PUT_BACK, _THE_NEW_FILE_TAKEN_AWAY],
                 id="diverged")
])
def test_a_difference_is_what_the_head_changed_since_the_lines_parted_and_what_it_lacks(
    stand_up: _StandsUp, base: str, head: str, relation: Relation, merge_base: str,
    files: list[_Read], taken_away: list[_Read]
) -> None:
    # What the head lacks of the base's line is read from the base to the
    # head, so every patch in the difference reads one way.
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: _as_read(host.reads.difference_between(base, head))) \
        .then(the_answer_was(
            (base, head, relation, merge_base, False, sorted(files), sorted(taken_away))
        ))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("base", "head", "paths"), [
    pytest.param(THE_FIRST_COMMIT, A_COMMIT_ON_IT, [A_FILE_ADDED, A_FILE], id="ahead"),
    pytest.param(A_COMMIT_ON_IT, A_COMMIT_ON_IT, [], id="identical"),
    pytest.param(A_COMMIT_ON_IT, THE_FIRST_COMMIT, [A_FILE_ADDED, A_FILE], id="behind"),
    pytest.param(A_COMMIT_ON_IT, A_COMMIT_BESIDE_IT, [ANOTHER_FILE, A_FILE_ADDED, A_FILE],
                 id="diverged")
])
def test_the_paths_changed_are_every_path_either_line_changed_since_they_parted(
    stand_up: _StandsUp, base: str, head: str, paths: list[str]
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: _sorted_or_none(host.reads.paths_changed_between(base, head))) \
        .then(the_answer_was(sorted(paths)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_fix_is_one_commit_on_its_base_holding_the_base_s_files_with_the_fix_over_them(
    stand_up: _StandsUp
) -> None:
    def write_then_read() -> tuple[str, dict[str, str], bool]:
        branch = host.writes.commit_to_new_branch(A_NEW_BRANCH, THE_FIRST_COMMIT, A_FIX,
                                                  SOME_MESSAGE)
        head = host.reads.head_of(A_NEW_BRANCH)

        return (branch, host.reads.source_at(head),
                host.reads.contains(A_NEW_BRANCH, THE_FIRST_COMMIT))

    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(write_then_read) \
        .then(the_answer_was((A_NEW_BRANCH, {**THE_FIRST_FILES, **A_FIX}, True)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_fix_asked_again_is_the_branch_it_already_wrote(stand_up: _StandsUp) -> None:
    def write_twice() -> tuple[str, bool]:
        host.writes.commit_to_new_branch(A_NEW_BRANCH, THE_FIRST_COMMIT, A_FIX, SOME_MESSAGE)
        first = host.reads.head_of(A_NEW_BRANCH)
        again = host.writes.commit_to_new_branch(A_NEW_BRANCH, THE_FIRST_COMMIT, A_FIX,
                                                 SOME_MESSAGE)

        return (again, host.reads.head_of(A_NEW_BRANCH) == first)

    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(write_twice) \
        .then(the_answer_was((A_NEW_BRANCH, True)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_branch_holding_other_work_is_refused_and_left_as_it_is(stand_up: _StandsUp) -> None:
    def write_then_read() -> tuple[Exception | None, str]:
        refused = attempting(lambda: host.writes.commit_to_new_branch(
            SOME_BRANCH, THE_FIRST_COMMIT, A_FIX, SOME_MESSAGE
        ))()

        return (refused, host.reads.head_of(SOME_BRANCH))

    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(write_then_read) \
        .then(all_of(
            lambda read: an_error_was_raised(BranchNotWritten)(read[0]),
            lambda read: the_answer_was(A_COMMIT_ON_IT)(read[1])
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_fix_on_a_commit_the_host_does_not_hold_is_refused(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(attempting(lambda: host.writes.commit_to_new_branch(A_NEW_BRANCH, NO_SUCH_COMMIT,
                                                                  A_FIX, SOME_MESSAGE))) \
        .then(an_error_was_raised(BranchNotWritten))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_proposal_is_a_draft_from_the_branch_onto_the_base(stand_up: _StandsUp) -> None:
    def propose_then_read() -> tuple[str, list[tuple[str, str, str, str, bool]]]:
        opened = host.writes.propose(SOME_BRANCH, SOME_BASE_BRANCH, SOME_TITLE, SOME_BODY)

        return (opened.branch, host.proposed())

    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(propose_then_read) \
        .then(the_answer_was(
            (SOME_BRANCH, [(SOME_BRANCH, SOME_BASE_BRANCH, SOME_TITLE, SOME_BODY, True)])
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_proposal_asked_again_is_the_one_already_open(stand_up: _StandsUp) -> None:
    def propose_twice() -> tuple[bool, int]:
        first = host.writes.propose(SOME_BRANCH, SOME_BASE_BRANCH, SOME_TITLE, SOME_BODY)
        again = host.writes.propose(SOME_BRANCH, SOME_BASE_BRANCH, SOME_TITLE, SOME_BODY)

        return (again == first, len(host.proposed()))

    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(propose_twice) \
        .then(the_answer_was((True, 1)))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("head", "base"), [
    pytest.param(NO_SUCH_BRANCH, SOME_BASE_BRANCH, id="a head that is no branch"),
    pytest.param(SOME_BRANCH, NO_SUCH_BRANCH, id="a base that is no branch")
])
def test_a_proposal_between_anything_but_two_branches_is_refused(
    stand_up: _StandsUp, head: str, base: str
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(attempting(lambda: host.writes.propose(head, base, SOME_TITLE, SOME_BODY))) \
        .then(an_error_was_raised(PullRequestNotOpened))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_revision_on_a_host_whose_pages_are_not_known_has_none(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED)) \
        .when(lambda: host.reads.where_to_read(A_REPOSITORY_ON_AN_UNKNOWN_HOST,
                                               A_COMMIT_ON_IT, None)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("ask", "failure"), [
    pytest.param(lambda host: host.reads.files_at(THE_FIRST_COMMIT), RepositoryUnreadable,
                 id="a read"),
    pytest.param(lambda host: host.writes.commit_to_new_branch(A_NEW_BRANCH, THE_FIRST_COMMIT,
                                                               A_FIX, SOME_MESSAGE),
                 BranchNotWritten, id="a branch"),
    pytest.param(lambda host: host.writes.propose(SOME_BRANCH, SOME_BASE_BRANCH, SOME_TITLE,
                                                  SOME_BODY),
                 PullRequestNotOpened, id="a proposal")
])
def test_a_host_nothing_reaches_fails_each_call_as_its_port_says(
    stand_up: _StandsUp, ask: Callable[[_Host], Any], failure: type[Exception]
) -> None:
    Scenario() \
        .given(host := stand_up(THE_SEED, unreachable=True)) \
        .when(attempting(lambda: ask(host))) \
        .then(an_error_was_raised(failure))


def _as_read(
    difference: SourceDifference
) -> tuple[str, str, Relation | None, str | None, bool, list[_Read], list[_Read]]:
    """A difference as a reader is handed it, each list in path order: the
    order is the host's, and no port promises one."""
    return (
        difference.base,
        difference.head,
        difference.relation,
        difference.merge_base,
        difference.more_files_than_listed,
        sorted(_as_read_file(each) for each in difference.files),
        sorted(_as_read_file(each) for each in difference.taken_away)
    )


def _as_read_file(changed: ChangedFile) -> _Read:
    lines = (changed.patch or "").split("\n")

    return (
        changed.path,
        changed.status,
        changed.previous_path,
        changed.copied_from,
        tuple(line[1:] for line in lines if line.startswith("-")),
        tuple(line[1:] for line in lines if line.startswith("+"))
    )


def _sorted_or_none(paths: list[str] | None) -> list[str] | None:
    """In path order, which no port promises - or `None` as it came."""
    return sorted(paths) if paths is not None else None
