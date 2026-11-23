"""What one deployment changed, as the read tier says it.

Here rather than in the read tier because three parties name it: the server that
says it, the client that carries it, and the Investigator that shows the lines
to a model and keeps the rest for the write-up.

A value rather than lines: each file the comparison named, with its status and
its patch, under the sentence saying which side of the comparison it is on. The
lines the model reads are rendered from it (`DeploymentChanges.said`), in a
layout declared once here, and every reader that has to find a file or a hunk
asks the value instead of parsing the lines back.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, model_validator

# How `DeploymentChanges.said` sets out a diff: every line under the one naming
# its file set in by two spaces - its patch lines, or the notice that it has
# none - and a hunk opened by git's `@@` line. Public because the lines are
# stored whole and read back as words by those that hold no value behind them:
# what a patch line quotes, and which revision the first line names.
PATCH_LINE_INDENT: Final = "  "
HUNK_HEADER: Final = "@@"


def a_changed_file_line(status: str, path: str) -> str:
    """The line of `DeploymentChanges.said` naming one file the diff changed:
    the status the comparison gave it - one word, as `modified` - and then its
    path."""
    return f"{status} {path}"


class DeploymentComparison(StrEnum):
    """Whether a deployment was compared against the one deployed before it -
    and, where it was not, why: no deployment has the revision asked about, or
    none came before it in the history."""

    COMPARED = "compared"
    NOT_DEPLOYED = "not-deployed"
    NOTHING_BEFORE_IT = "nothing-before-it"


class NoDiff(StrEnum):
    """Why a file the comparison named carries no patch: it was a copy, which
    the comparison shows only against its source, or the comparison carried
    none - a file that is not text, or a change too large to list."""

    COPY = "copy"
    NONE_CARRIED = "none-carried"


class FileRead(BaseModel):
    """One file the comparison named: its status, its path, and its patch's
    lines - or why it has none (`no_diff`), or neither, where the answer's
    budget for patch lines ran out before it and it is named alone."""

    model_config = ConfigDict(frozen=True)

    path: str
    status: str
    patch: list[str] | None = None
    no_diff: NoDiff | None = None
    copied_from: str | None = None

    @model_validator(mode="after")
    def _says_one_thing_of_its_patch(self) -> FileRead:
        """A patch, or why there is none, never both; and the file it was
        copied from only on a copy, which always names it."""
        if self.patch is not None and self.no_diff is not None:
            raise ValueError(f"[{self.path}] carries a patch and says it has none")
        if (self.no_diff is NoDiff.COPY) != (self.copied_from is not None):
            raise ValueError(f"[{self.path}] names the file it was copied from only where it "
                             f"is a copy, and says {self.no_diff!r} with {self.copied_from!r}")
        return self

    @property
    def hunks(self) -> list[list[str]]:
        """The patch cut into its hunks: each a run of patch lines with their
        marker, the `@@` line that opens one not among them - its text is git's
        nearest preceding section line, not the one the hunk is in. No hunk
        where there is no patch."""
        hunks: list[list[str]] = []
        current: list[str] | None = None
        for line in self.patch or []:
            if current is None or line.startswith(HUNK_HEADER):
                current = []
                hunks.append(current)
            if not line.startswith(HUNK_HEADER):
                current.append(line)

        return hunks

    @property
    def said(self) -> list[str]:
        """The file as the lines say it: the line naming it, and under it its
        patch, or the notice that it has none."""
        named = [a_changed_file_line(self.status, self.path)]

        if self.no_diff is NoDiff.COPY:
            return [*named, f"{PATCH_LINE_INDENT}(no diff: it was a copy of {self.copied_from}, "
                            f"and the comparison shows only how the copy differed from it)"]

        if self.no_diff is NoDiff.NONE_CARRIED:
            return [*named, f"{PATCH_LINE_INDENT}(no diff: the comparison carries none for this "
                            "file - it is not text, or its change was too large to list)"]

        return [*named, *(f"{PATCH_LINE_INDENT}{line}" for line in self.patch or [])]


class Side(BaseModel):
    """One side of a comparison: the sentence saying what it is - none for a
    deploy ahead of the one before it, which is said as it always was - and the
    files on it, in the order the comparison named them."""

    model_config = ConfigDict(frozen=True)

    sentence: str | None = None
    files: list[FileRead] = []


class DeploymentChanges(BaseModel):
    """What one deployment changed: the opening lines - the header naming both
    revisions, or the one answer that is no comparison - the sides of the
    comparison, and the notices of what one answer could not carry; whether
    they name every file its revision differs in from the one deployed before
    it; and whether there was a comparison behind them at all.

    `lists_every_file` is what lets a reader say of a file the lines do not
    name that it is as it was at the revision compared against - true only
    where nothing was cut off, on either side of the comparison, and every file
    found was named. An answer of no files is one listing every file there is;
    an answer with no comparison behind it - no such deployment, or none before
    it - lists none, and says nothing of any file.

    `comparison` is what tells those two apart: only a comparison is a diff,
    and every reader but the model says the others in its own words. Compared
    by default, as every answer carried before it was claimed to be.

    Every part defaulted, so a walk's checkpoint written before they were
    carried revives as an answer naming no file, which credits no deploy.
    """

    opening: list[str] = []
    sides: list[Side] = []
    notices: list[str] = []
    lists_every_file: bool = False
    comparison: DeploymentComparison = DeploymentComparison.COMPARED

    @property
    def said(self) -> list[str]:
        """The lines a model reads: the opening, each side's sentence and its
        files, and the notices - the one rendering of the value, so the lines
        and what a reader asks of the value never disagree."""
        return [*self.opening,
                *(line for side in self.sides
                  for line in ([side.sentence] if side.sentence is not None else [])
                  + [said for read in side.files for said in read.said]),
                *self.notices]

    @property
    def files(self) -> list[FileRead]:
        """Every file the comparison named, both sides, in order - a file both
        sides changed listed twice, once on each."""
        return [read for side in self.sides for read in side.files]


def the_changed_file_it_names(subject: str, paths: list[str]) -> str | None:
    """The file `subject` names among `paths` - the files a diff changed - or
    `None` where it names none.

    The longest start of the subject that is one of them, ending where the
    subject does or at a colon or a space: a setting is named with the file it
    lives in, and a path can hold a space of its own. Declared once, because
    the walk and the write-up both find the deploy that carried a file by it,
    and a subject read two ways would credit two different deploys."""
    ends = [at for at, character in enumerate(subject) if character in WHAT_ENDS_A_FILE]
    for end in sorted([*ends, len(subject)], reverse=True):
        if subject[:end] in paths:
            return subject[:end]

    return None


# What sets a file off from the key in it, where a setting is named with the
# file it lives in: `deploy/values-production.yaml:cache.port`, or the same
# with a space.
WHAT_ENDS_A_FILE: Final = ": "
