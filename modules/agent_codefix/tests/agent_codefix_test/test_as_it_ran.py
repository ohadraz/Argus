"""The files Code-Fix's reading names, read again at the revision that ran.

Code-Fix reads a branch, and the revision running when the alert fired may not
be on it. A write-up then called the file the cause turned on "Code-Fix's
reading, nothing ran" - true of where the text came from, and the only thing it
could say, because nothing in the record held the file as it ran. So once Code-Fix
has answered, each file its reading names is read again at that revision: the
same as the branch read, and the reading stands for it; different, or not there
to compare, and the file as it ran is kept for the write-up to show.

Only reads, after the model's answer - nothing here is asked of the model.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from agent_codefix.as_it_ran import the_files_as_they_ran, the_uses_as_they_ran
from argus_core.models import CodeUse, FileAsItRan
from argus_testkit import Scenario, the_answer_was

SOME_BRANCH = "main"
SOME_REVISION = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"
SOME_PATH = "deploy/scrape.yaml"
SOME_OTHER_PATH = "deploy/values-production.yaml"
SOME_CONTENT = "selector:\n  port: metrics\n"
SOME_OTHER_CONTENT = "selector:\n  port: metrics\n  interval: 15s\n"

A_READING_NAMING_IT = f"The scrape config in {SOME_PATH} selects the port by its old name."

SOME_USE = CodeUse(name="month", path=SOME_PATH, line=2, function="reconcile",
                   does="compares it with bought(account)")


@pytest.mark.unit
def test_a_file_as_it_ran_that_matches_the_branch_read_stands_on_the_reading() -> None:
    # Nothing to show: what Code-Fix read is what ran.
    list_files, read_file = _a_repository(on_the_branch={SOME_PATH: SOME_CONTENT},
                                          at_the_revision={SOME_PATH: SOME_CONTENT})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(A_READING_NAMING_IT, branch=SOME_BRANCH,
                                          deployed=SOME_REVISION, list_files=list_files,
                                          read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(path=SOME_PATH, revision=SOME_REVISION,
                                        as_read=True, content=None)])
        )


@pytest.mark.unit
def test_a_file_as_it_ran_that_differs_from_the_branch_read_is_kept_whole() -> None:
    # The reading is of other text, and the write-up has nothing else that
    # shows what ran.
    list_files, read_file = _a_repository(on_the_branch={SOME_PATH: SOME_OTHER_CONTENT},
                                          at_the_revision={SOME_PATH: SOME_CONTENT})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(A_READING_NAMING_IT, branch=SOME_BRANCH,
                                          deployed=SOME_REVISION, list_files=list_files,
                                          read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(path=SOME_PATH, revision=SOME_REVISION,
                                        as_read=False, content=SOME_CONTENT)])
        )


@pytest.mark.unit
def test_a_file_the_branch_does_not_hold_is_kept_as_it_ran() -> None:
    # Nothing to compare it with, so nothing says the reading stands for it.
    # The file as it ran is true whatever the branch holds.
    list_files, read_file = _a_repository(on_the_branch={},
                                          at_the_revision={SOME_PATH: SOME_CONTENT})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(A_READING_NAMING_IT, branch=SOME_BRANCH,
                                          deployed=SOME_REVISION, list_files=list_files,
                                          read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(path=SOME_PATH, revision=SOME_REVISION,
                                        as_read=False, content=SOME_CONTENT)])
        )


@pytest.mark.unit
def test_a_long_file_as_it_ran_is_cut_and_says_where() -> None:
    # Read to its end, a lockfile named in passing would fill the brief.
    some_long_content = "".join(f"line {number}\n" for number in range(1, 251))
    list_files, read_file = _a_repository(on_the_branch={},
                                          at_the_revision={SOME_PATH: some_long_content})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(A_READING_NAMING_IT, branch=SOME_BRANCH,
                                          deployed=SOME_REVISION, list_files=list_files,
                                          read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(
                path=SOME_PATH, revision=SOME_REVISION, as_read=False,
                content="".join(f"line {number}\n" for number in range(1, 201))
                        + "(cut at line 200 of 250)")])
        )


@pytest.mark.unit
def test_a_file_whose_read_at_the_revision_fails_is_left_out() -> None:
    # Never guessed: a file nobody read as it ran is not shown as one.
    list_files, read_file = _a_repository(
        on_the_branch={SOME_PATH: SOME_CONTENT, SOME_OTHER_PATH: SOME_CONTENT},
        at_the_revision={SOME_OTHER_PATH: SOME_OTHER_CONTENT},
        listed_at_the_revision=[SOME_PATH, SOME_OTHER_PATH])

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(f"{A_READING_NAMING_IT} So does {SOME_OTHER_PATH}.",
                                          branch=SOME_BRANCH, deployed=SOME_REVISION,
                                          list_files=list_files, read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(path=SOME_OTHER_PATH, revision=SOME_REVISION,
                                        as_read=False, content=SOME_OTHER_CONTENT)])
        )


@pytest.mark.unit
def test_a_file_the_revision_does_not_hold_is_not_read() -> None:
    # Named against the listing at the revision, as Code-Fix's own names are
    # against the branch's: a name that revision has no file for is not one.
    list_files, read_file = _a_repository(on_the_branch={SOME_PATH: SOME_CONTENT},
                                          at_the_revision={})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(A_READING_NAMING_IT, branch=SOME_BRANCH,
                                          deployed=SOME_REVISION, list_files=list_files,
                                          read_file=read_file)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_a_file_the_reading_calls_only_by_a_word_is_not_read_as_it_ran() -> None:
    # Each file read as it ran is said to be one the reading names. The word
    # "endpoints" - of a ServiceMonitor's, in a sentence about deploy/scrape.yaml -
    # was taken for src/io_shop/endpoints.py, a file the reading never mentioned.
    some_code = "src/io_shop/endpoints.py"
    list_files, read_file = _a_repository(
        on_the_branch={SOME_PATH: SOME_CONTENT, some_code: "dont care"},
        at_the_revision={SOME_PATH: SOME_CONTENT, some_code: "dont care"})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(f"Every port under the endpoints in {SOME_PATH}.",
                                          branch=SOME_BRANCH, deployed=SOME_REVISION,
                                          list_files=list_files, read_file=read_file)
        ) \
        .then(
            the_answer_was([FileAsItRan(path=SOME_PATH, revision=SOME_REVISION,
                                        as_read=True, content=None)])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("reading", "deployed"), [
    (None, SOME_REVISION),
    (A_READING_NAMING_IT, None)
], ids=["no-reading", "no-revision-known"])
def test_with_no_reading_or_no_revision_nothing_is_read(reading: str | None,
                                                        deployed: str | None) -> None:
    list_files, read_file = _a_repository(on_the_branch={SOME_PATH: SOME_OTHER_CONTENT},
                                          at_the_revision={SOME_PATH: SOME_CONTENT})

    Scenario() \
        .when(
            lambda: the_files_as_they_ran(reading, branch=SOME_BRANCH, deployed=deployed,
                                          list_files=list_files, read_file=read_file)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("on_the_branch", "at_the_revision", "as_read"), [
    ({SOME_PATH: SOME_CONTENT}, {SOME_PATH: SOME_CONTENT}, True),
    ({SOME_PATH: SOME_OTHER_CONTENT}, {SOME_PATH: SOME_CONTENT}, False),
    ({SOME_PATH: SOME_CONTENT}, {}, False),
    ({}, {SOME_PATH: SOME_CONTENT}, False)
], ids=["the-same", "different", "not-read-at-the-revision", "not-read-on-the-branch"])
def test_a_use_outside_the_patch_says_whether_its_file_ran_as_the_branch_holds_it(
        on_the_branch: dict[str, str], at_the_revision: dict[str, str], as_read: bool) -> None:
    # The lines outside the patch are read on the branch, and a write-up applied
    # them to what ran - true only where their file ran as the branch holds it.
    # A file not read on both sides is never said to have.
    _, read_file = _a_repository(on_the_branch=on_the_branch, at_the_revision=at_the_revision)

    Scenario() \
        .when(
            lambda: the_uses_as_they_ran([SOME_USE], branch=SOME_BRANCH,
                                         deployed=SOME_REVISION, read_file=read_file)
        ) \
        .then(
            the_answer_was([SOME_USE.model_copy(update={"revision": SOME_REVISION,
                                                        "as_read": as_read})])
        )


@pytest.mark.unit
def test_each_use_outside_the_patch_is_said_of_by_its_own_file() -> None:
    some_other_use = CodeUse(name="month", path=SOME_OTHER_PATH, line=5, function=None,
                             does="returns it")
    _, read_file = _a_repository(
        on_the_branch={SOME_PATH: SOME_CONTENT, SOME_OTHER_PATH: SOME_CONTENT},
        at_the_revision={SOME_PATH: SOME_CONTENT, SOME_OTHER_PATH: SOME_OTHER_CONTENT})

    Scenario() \
        .when(
            lambda: the_uses_as_they_ran([SOME_USE, some_other_use], branch=SOME_BRANCH,
                                         deployed=SOME_REVISION, read_file=read_file)
        ) \
        .then(
            the_answer_was([
                SOME_USE.model_copy(update={"revision": SOME_REVISION, "as_read": True}),
                some_other_use.model_copy(update={"revision": SOME_REVISION, "as_read": False})
            ])
        )


@pytest.mark.unit
def test_uses_outside_the_patch_with_no_revision_known_to_have_run_are_compared_with_none() -> None:
    _, read_file = _a_repository(on_the_branch={SOME_PATH: SOME_CONTENT},
                                 at_the_revision={SOME_PATH: SOME_CONTENT})

    Scenario() \
        .when(
            lambda: the_uses_as_they_ran([SOME_USE], branch=SOME_BRANCH, deployed=None,
                                         read_file=read_file)
        ) \
        .then(
            the_answer_was([SOME_USE])
        )


def _a_repository(on_the_branch: dict[str, str],
                  at_the_revision: dict[str, str],
                  listed_at_the_revision: list[str] | None = None
                  ) -> tuple[_ListFiles, _ReadFile]:
    """A repository holding these files on the branch and at the revision -
    listed at the revision as held there unless said, and raising for a file
    a ref does not hold, as the read tier does."""
    held = {SOME_BRANCH: on_the_branch, SOME_REVISION: at_the_revision}
    listed = {SOME_BRANCH: list(on_the_branch),
              SOME_REVISION: (listed_at_the_revision if listed_at_the_revision is not None
                              else list(at_the_revision))}

    def list_files(ref: str, /) -> list[str]:
        return listed[ref]

    def read_file(path: str, ref: str, /) -> str:
        if path not in held[ref]:
            raise RuntimeError(f"no {path} at {ref}")

        return held[ref][path]

    return list_files, read_file


type _ListFiles = Callable[[str], list[str]]
type _ReadFile = Callable[[str, str], str]
