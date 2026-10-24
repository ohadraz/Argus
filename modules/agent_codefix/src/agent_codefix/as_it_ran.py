"""The files Code-Fix's reading names, read again at the revision that ran.

Code-Fix reads a branch, and the revision running when the alert fired may not
be on it. A write-up then called the file the cause turned on "Code-Fix's
reading, nothing ran" - true of where the text came from, and the only thing it
could say, because nothing in the record held the file as it ran. So once
Code-Fix has answered, each file its reading names is read again at that
revision: the same as the branch read, and the reading stands for it; different,
or not there to compare, and the file as it ran is kept for the write-up to show.

Only reads, after the model's answer - nothing here is asked of the model, so no
request Code-Fix sends changes.
"""

from __future__ import annotations

import logging
from typing import Final

from argus_core.models import FileAsItRan

from agent_codefix.naming import files_named_in
from agent_codefix.retrieval import FileLister, FileReader

logger = logging.getLogger(__name__)

# How much of a file as it ran is kept. A file the reading names in passing - a
# lockfile, a generated schema - read to its end would fill the brief.
_LINES_KEPT: Final = 200


def the_files_as_they_ran(reading: str | None,
                          *,
                          branch: str,
                          deployed: str | None,
                          list_files: FileLister,
                          read_file: FileReader) -> list[FileAsItRan]:
    """Each file `reading` names that `deployed` holds, as it ran there, and
    whether that is the file `branch` holds.

    Named against the listing at the revision, as the opening's names are
    against the branch's: a name that revision has no file for is not one. And
    only a file the reading writes as one, never a bare word that is a file's
    stem: each file here is said to be one the reading names, and "endpoints",
    of a ServiceMonitor's, was said to name a file the reading never mentioned.

    A file whose read at the revision fails is left out - never guessed: a file
    nobody read as it ran is not shown as one. A read on the branch that fails
    leaves nothing to compare with, so the file is kept as it ran: that is true
    whatever the branch holds, and only a match says the reading stands for it.

    Nothing where there is no reading, or no revision known to have run.
    """
    if reading is None or deployed is None:
        return []

    try:
        listing = list_files(deployed)
    except Exception:
        logger.warning("could not list the revision that ran", exc_info=True)

        return []

    return [ran for path in files_named_in([reading], listing, by_stem=False).held
            if (ran := _as_it_ran(path, branch, deployed, read_file)) is not None]


def _as_it_ran(path: str,
               branch: str,
               deployed: str,
               read_file: FileReader) -> FileAsItRan | None:
    """One file at the revision that ran, compared with the branch's - or
    `None` where it could not be read there."""
    try:
        ran = read_file(path, deployed)
    except Exception:
        logger.warning("could not read a file as it ran", extra={"path": path}, exc_info=True)

        return None

    try:
        read = read_file(path, branch)
    except Exception:
        read = None

    if read == ran:
        return FileAsItRan(path=path, revision=deployed, as_read=True, content=None)

    return FileAsItRan(path=path, revision=deployed, as_read=False, content=_cut(ran))


def _cut(content: str) -> str:
    """The file to its first lines kept, saying where it was cut and of how
    many - or whole, where it is no longer than that."""
    lines = content.splitlines(keepends=True)

    if len(lines) <= _LINES_KEPT:
        return content

    return "".join(lines[:_LINES_KEPT]) + f"(cut at line {_LINES_KEPT} of {len(lines)})"
