"""What one deployment changed, as a value and as the lines a model reads.

The read tier builds the value and renders it once; the walk and the write-up
ask the value which files a deploy changed and what changed inside them. So the
lines have to say exactly what the value holds, and the value has to refuse to
say two things of one file.
"""

from __future__ import annotations

from typing import Final

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core.models import (
    DeploymentChanges,
    FileRead,
    NoDiff,
    Side,
    the_changed_file_it_names,
)
from pydantic import ValidationError

SOME_PATH: Final = "deploy/values-production.yaml"
SOME_PATH_WITH_A_SPACE: Final = "docs/release notes.md"
SOME_OTHER_PATH: Final = "src/io_shop/purchase_ledger.py"
# A setting named with the file it lives in, as a candidate blames one.
SOME_KEY: Final = "cache.port"
SOME_FLAG: Final = "monthly-spend-feature"
SOME_STATUS: Final = "modified"
SOME_SOURCE: Final = "deploy/values-staging.yaml"
SOME_HEADER: Final = "@@ -1,2 +1,2 @@ cache:"
SOME_LATER_HEADER: Final = "@@ -9 +9 @@"
SOME_REMOVED_LINE: Final = "-  model: v1"
SOME_ADDED_LINE: Final = "+  model: v2"
SOME_CONTEXT_LINE: Final = "   port: 6379"
SOME_OPENING: Final = ("Deployment of revision 7c3ca00 to io-shop, compared against 1a2b3c4 - "
                       "the revision deployed before it.")
SOME_SENTENCE: Final = "Behind the revision deployed before it:"
SOME_NOTICE: Final = "(further files were not listed)"


@pytest.mark.unit
def test_a_file_carrying_a_patch_and_saying_it_has_none_is_refused() -> None:
    # A reader asking for its hunks and a reader asking why it has none would
    # each be told something true of a different file.
    Scenario() \
        .given(SOME_PATH) \
        .when(attempting(lambda: FileRead(path=SOME_PATH, status=SOME_STATUS,
                                          patch=[SOME_HEADER, SOME_ADDED_LINE],
                                          no_diff=NoDiff.NONE_CARRIED))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
@pytest.mark.parametrize(("no_diff", "copied_from"), [(NoDiff.COPY, None),
                                                      (NoDiff.NONE_CARRIED, SOME_SOURCE),
                                                      (None, SOME_SOURCE)],
                         ids=["a-copy-naming-no-source", "a-source-on-a-file-with-none-carried",
                              "a-source-on-a-file-named-alone"])
def test_only_a_copy_names_the_file_it_was_copied_from(no_diff: NoDiff | None,
                                                       copied_from: str | None) -> None:
    # A copy's notice says what it was copied from, so a copy naming nothing
    # renders a notice naming `None`; anything else naming a source claims a
    # copy the comparison never reported.
    Scenario() \
        .given(no_diff) \
        .when(attempting(lambda: FileRead(path=SOME_PATH, status=SOME_STATUS,
                                          no_diff=no_diff, copied_from=copied_from))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
def test_a_patch_is_cut_into_its_hunks_at_each_header() -> None:
    # A setting moves within one hunk: a removed line and an added one in two
    # hunks are two edits, not one. The `@@` line opens a hunk and is not in it
    # - its text is git's nearest section line, not the hunk's own.
    Scenario() \
        .given(a_file := FileRead(path=SOME_PATH, status=SOME_STATUS,
                                  patch=[SOME_HEADER, SOME_REMOVED_LINE, SOME_ADDED_LINE,
                                         SOME_LATER_HEADER, SOME_CONTEXT_LINE])) \
        .when(lambda: a_file.hunks) \
        .then(the_answer_was([[SOME_REMOVED_LINE, SOME_ADDED_LINE], [SOME_CONTEXT_LINE]]))


@pytest.mark.unit
@pytest.mark.parametrize("no_diff", [NoDiff.NONE_CARRIED, None],
                         ids=["none-carried", "named-alone"])
def test_a_file_with_no_patch_has_no_hunks(no_diff: NoDiff | None) -> None:
    # Its notice is not a patch line, so no setting is read as moving by it -
    # and a file the line budget cut is named, with nothing inside it to read.
    Scenario() \
        .given(a_file := FileRead(path=SOME_PATH, status=SOME_STATUS, no_diff=no_diff)) \
        .when(lambda: a_file.hunks) \
        .then(the_answer_was([]))


@pytest.mark.unit
@pytest.mark.parametrize(("a_file", "said"), [
    (FileRead(path=SOME_PATH, status=SOME_STATUS, patch=[SOME_HEADER, SOME_ADDED_LINE]),
     [f"{SOME_STATUS} {SOME_PATH}", f"  {SOME_HEADER}", f"  {SOME_ADDED_LINE}"]),
    (FileRead(path=SOME_PATH, status=SOME_STATUS, no_diff=NoDiff.COPY, copied_from=SOME_SOURCE),
     [f"{SOME_STATUS} {SOME_PATH}",
      f"  (no diff: it was a copy of {SOME_SOURCE}, and the comparison shows only how the "
      f"copy differed from it)"]),
    (FileRead(path=SOME_PATH, status=SOME_STATUS, no_diff=NoDiff.NONE_CARRIED),
     [f"{SOME_STATUS} {SOME_PATH}",
      "  (no diff: the comparison carries none for this file - it is not text, or its "
      "change was too large to list)"]),
    (FileRead(path=SOME_PATH, status=SOME_STATUS),
     [f"{SOME_STATUS} {SOME_PATH}"])
], ids=["a-patch", "a-copy", "none-carried", "named-alone"])
def test_each_shape_of_file_is_said_as_the_model_has_always_read_it(
        a_file: FileRead, said: list[str]) -> None:
    # Byte for byte: these lines are what recorded answers were replayed
    # against, and a rendering that drifts by a space is a model input nobody
    # chose to change.
    Scenario() \
        .given(a_file) \
        .when(lambda: a_file.said) \
        .then(the_answer_was(said))


@pytest.mark.unit
def test_a_comparison_is_said_opening_first_then_each_side_then_its_notices() -> None:
    # A side with no sentence - a deploy ahead of the one before it - is said
    # as it always was, its files straight under the opening.
    Scenario() \
        .given(changes := DeploymentChanges(
            opening=[SOME_OPENING],
            sides=[Side(files=[FileRead(path=SOME_PATH, status=SOME_STATUS)]),
                   Side(sentence=SOME_SENTENCE,
                        files=[FileRead(path=SOME_OTHER_PATH, status=SOME_STATUS)])],
            notices=[SOME_NOTICE])) \
        .when(lambda: changes.said) \
        .then(the_answer_was([SOME_OPENING,
                              f"{SOME_STATUS} {SOME_PATH}",
                              SOME_SENTENCE,
                              f"{SOME_STATUS} {SOME_OTHER_PATH}",
                              SOME_NOTICE]))


@pytest.mark.unit
def test_every_file_on_either_side_is_among_its_files_in_order() -> None:
    # A file both sides changed is listed once on each: the walk credits a
    # deploy with a file it names on either side.
    Scenario() \
        .given(changes := DeploymentChanges(
            sides=[Side(files=[a_file := FileRead(path=SOME_PATH, status=SOME_STATUS),
                               another_file := FileRead(path=SOME_OTHER_PATH,
                                                        status=SOME_STATUS)]),
                   Side(sentence=SOME_SENTENCE, files=[a_file])])) \
        .when(lambda: changes.files) \
        .then(the_answer_was([a_file, another_file, a_file]))


@pytest.mark.unit
@pytest.mark.parametrize("subject", [SOME_PATH, f"{SOME_PATH}:{SOME_KEY}",
                                     f"{SOME_PATH} {SOME_KEY}"],
                         ids=["the-file", "a-key-after-a-colon", "a-key-after-a-space"])
def test_a_subject_names_the_changed_file_it_starts_with(subject: str) -> None:
    # A candidate blames a file, or a setting with the file it lives in. Either
    # names the file a diff changed, and the walk and the write-up both find
    # what carried it by that file - so the two read a subject one way.
    Scenario() \
        .given(subject) \
        .when(lambda: the_changed_file_it_names(subject, [SOME_PATH])) \
        .then(the_answer_was(SOME_PATH))


@pytest.mark.unit
def test_a_path_with_a_space_of_its_own_is_named_whole() -> None:
    # The longest start that is a changed file wins, so a space inside a path
    # does not cut it short.
    Scenario() \
        .given(SOME_PATH_WITH_A_SPACE) \
        .when(lambda: the_changed_file_it_names(f"{SOME_PATH_WITH_A_SPACE}:{SOME_KEY}",
                                                [SOME_PATH_WITH_A_SPACE])) \
        .then(the_answer_was(SOME_PATH_WITH_A_SPACE))


@pytest.mark.unit
@pytest.mark.parametrize("subject", [SOME_SOURCE, SOME_PATH.rpartition("/")[2], SOME_FLAG],
                         ids=["another-file", "the-end-of-its-path", "a-flag"])
def test_a_subject_naming_no_changed_file_names_none(subject: str) -> None:
    # Only a file the diff names among those it changed, by the whole of its
    # path: another file, the tail of this one's path or a flag is no file the
    # deploy changed.
    Scenario() \
        .given(subject) \
        .when(lambda: the_changed_file_it_names(subject, [SOME_PATH])) \
        .then(the_answer_was(None))
