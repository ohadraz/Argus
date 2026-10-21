"""What changed between two commits, as paths (spec §11).

The question that keeps a catch-up pass from considering a repository entire.
Everything unchanged is already in the index under an id derived from what it
says, so a full pass embeds nothing it has seen before - but it still asks the
store, once per file, whether it holds it. At forty files that is free; at a
hundred thousand it is a hundred thousand round trips a cycle, and this turns
them into the handful that moved.

Beside `reading.py` rather than inside it: both read the same repository with
the same credential and raise the same failure, and one answers what the code
says where the other answers what about it is new.

Two answers here are not the same and must never be confused. Nothing changed
is a fact. Not being able to say what changed is the absence of one, and the
caller's move for it is to reconsider everything - which is why it comes back
as `None` rather than as an empty list nobody can tell from the first.
"""

from __future__ import annotations

from typing import Any, Final

import httpx2

from repository_source.reading import (
    ACCEPT_HEADER,
    HttpGet,
    RepositorySourceSettings,
    RepositoryUnreadable,
)

# GitHub's wire vocabulary for a comparison, named for the fields that carry
# it. `PREVIOUS_FILENAME_FIELD` is the one a reader forgets: it appears only on
# a rename, and it is the half of that rename the index has to be told about.
FILES_FIELD: Final = "files"
FILENAME_FIELD: Final = "filename"
PREVIOUS_FILENAME_FIELD: Final = "previous_filename"

# How the two commits are named in the path: base first, three dots, head.
# Ordered, and it matters - reversed, the comparison describes undoing the push
# rather than making it.
BETWEEN: Final = "..."

# How the head of a comparison stands to its base, in GitHub's words: past it,
# the same commit, short of it, or on another line from it. The first two put
# the base in the head's history.
RELATION_FIELD: Final = "status"
AHEAD: Final = "ahead"
IDENTICAL: Final = "identical"
BEHIND: Final = "behind"
DIVERGED: Final = "diverged"

# Where the two commits' lines of history part: the commit the comparison's
# files are listed from.
MERGE_BASE_FIELD: Final = "merge_base_commit"
SHA_FIELD: Final = "sha"

# How many files one comparison will list. GitHub's own number: "the list of
# changed files is only shown on the first page of results, and it includes up
# to 300 changed files for the entire comparison" - and there is no flag saying
# it stopped there. A list this long is therefore not a list of what changed,
# it is the first three hundred of them, and the two are indistinguishable from
# here.
MOST_FILES_A_COMPARISON_LISTS: Final = 300

COMPARISON_TIMEOUT_SECONDS: Final = 10.0


def paths_changed_between(base: str,
                          head: str,
                          settings: RepositorySourceSettings,
                          get: HttpGet = httpx2.get) -> list[str] | None:
    """Every path that differs between the two commits, or `None` for "I cannot
    say".

    A rename contributes both of its paths. It is a deletion and an addition
    wearing one entry, and named only by where the file went, the passages
    under where it was are never forgotten - so the index goes on answering
    with a file the repository no longer has.

    Where the head is not ahead of the base, asked the other way round as
    well. A comparison lists what the head changed since the two commits'
    lines parted, and a force-push that dropped the base's side lists nothing
    of what it dropped - so the passages for it were left standing, and the
    index recorded itself current over them. Both sides are named: every path
    that can differ between the two.

    `None` where either side is at the ceiling of what the API will list.
    Read as complete, a rebase or a formatting sweep would leave most of the
    repository unindexed while the watermark recorded the index as current -
    absence of evidence arriving as evidence of absence, which this codebase
    refuses everywhere else.

    Raises `RepositoryUnreadable` when the comparison could not be made, for
    the reason reading the source does: an empty answer would have a catch-up
    pass record the index as current over passages nobody updated.
    """
    compared = _compared(base, head, settings, get)
    sides = [compared.get(FILES_FIELD, [])]

    if compared.get(RELATION_FIELD) in (BEHIND, DIVERGED):
        sides.append(_compared(head, base, settings, get).get(FILES_FIELD, []))

    if any(len(files) >= MOST_FILES_A_COMPARISON_LISTS for files in sides):
        return None

    return list(dict.fromkeys(
        path
        for files in sides
        for entry in files
        for path in (entry.get(FILENAME_FIELD), entry.get(PREVIOUS_FILENAME_FIELD))
        if isinstance(path, str)
    ))


def _compared(base: str,
              head: str,
              settings: RepositorySourceSettings,
              get: HttpGet) -> dict[str, Any]:
    """GitHub's comparison of the two commits, as it sent it."""
    url = (
        f"{settings.github_api_url}/repos/{settings.github_repository}"
        f"/compare/{base}{BETWEEN}{head}"
    )

    try:
        response = get(
            url, headers=_headers(settings), timeout=COMPARISON_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        compared: dict[str, Any] = response.json()
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not compare [{base}] with [{head}] in "
            f"[{settings.github_repository}]: {error}"
        ) from error

    return compared


def _headers(settings: RepositorySourceSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_read_token}",
        "Accept": ACCEPT_HEADER
    }
