"""What changed between two commits, with the change itself (spec §11, §16).

`comparing.py` answers which paths differ, which is all a catch-up pass needs -
everything it names is re-read from the repository anyway. This answers what
differs inside them, for a reader who will not be re-reading anything: an
investigation deciding whether a deployment shipped bad code or bad
configuration, where the whole distinction is inside the diff.

The two part company at the ceiling, deliberately. GitHub lists at most three
hundred files for a comparison and gives no flag saying it stopped, so a pass
that read such a list as complete would index three hundred files and record the
index as current over the rest - which is why `paths_changed_between` refuses to
answer at all. An investigation has no such trap. Three hundred files *is* the
finding, and it is a finding that answers the question being asked: a deployment
that changed a repository entire certainly changed code. So the answer comes back
with the list it got and says that there were more.

No scope, and none to pass. The read tier narrows what it searches and what it
indexes to the directories holding the service's own source, which is right for
reading code and inverting here: the configuration a deployment ships lives
outside the source tree by definition, so a narrowed comparison hides the one file
that answers the question - and hides it as an empty answer, which reads as a
deployment that changed nothing.

Nothing here decides what a path *means*. Which directories hold configuration
belongs to the repository being read and differs between repositories, so a path
labelled "code" or "config" here would be this module deciding something it cannot
know - wrongly, the first time somebody keeps their values beside their source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx2

from repository_source.comparing import (
    BETWEEN,
    FILENAME_FIELD,
    FILES_FIELD,
    MOST_FILES_A_COMPARISON_LISTS,
    PREVIOUS_FILENAME_FIELD,
)
from repository_source.reading import (
    ACCEPT_HEADER,
    HttpGet,
    RepositorySourceSettings,
    RepositoryUnreadable,
)

# The two fields of a comparison entry that `comparing.py` has no use for. The
# status is how the API says whether the file arrived, left, moved or merely
# changed; the patch is the change itself, and is the reason this module exists.
STATUS_FIELD: Final = "status"
PATCH_FIELD: Final = "patch"

COMPARISON_TIMEOUT_SECONDS: Final = 20.0


@dataclass(frozen=True)
class ChangedFile:
    """One file a comparison names, and what happened inside it.

    `patch` is optional because the API omits it rather than sending an empty
    one: a file that is not text has no diff to show, and a diff the API judges
    too large is left out with every other field present. An empty string would
    say the file was touched and nothing happened to it, which is a different
    fact and one a reader counting changed source would count the wrong way.

    `previous_path` is set only on a rename, and is the half of a rename a reader
    otherwise never learns. Named only by where it went, a file that moved is
    indistinguishable from one that appeared - and the two say different things
    about what a deployment did.

    `status` is carried as the API spelled it, unmapped. Nothing here branches on
    it, and a vocabulary of this module's own would be a second spelling for a
    reader to learn for no gain.
    """

    path: str
    status: str
    patch: str | None = None
    previous_path: str | None = None


@dataclass(frozen=True)
class SourceDifference:
    """Everything that differs between two commits, as far as it could be listed.

    Carries the two revisions it is a difference of, because what reads it is a
    model rather than the caller that asked: a diff that does not say what it is a
    diff of is one the reader has to trust it was handed correctly.

    `more_files_than_listed` is the flag that keeps a cut-off answer from reading
    as a complete one. A short list is what both look like, and a deployment that
    rewrote a repository would otherwise arrive as one that touched the handful of
    files that happened to fit.
    """

    base: str
    head: str
    files: tuple[ChangedFile, ...]
    more_files_than_listed: bool


def the_difference_between(base: str,
                           head: str,
                           settings: RepositorySourceSettings,
                           get: HttpGet = httpx2.get) -> SourceDifference:
    """Every file that differs between the two commits, and what changed in each.

    Ordered, and it matters: reversed, the difference describes putting a
    deployment back rather than making it, and a port that moved reads as a port
    that was fixed.

    Raises `RepositoryUnreadable` when the comparison could not be made, for the
    reason every other reader here does. "This deployment changed nothing" rules a
    deployment out as a cause, and a repository nobody could reach supports no such
    conclusion - so it must not arrive looking like one that does.

    A longer timeout than `paths_changed_between`'s, because the answer is larger
    by the size of every patch in it and a comparison that arrives slowly is still
    the answer somebody is waiting for.
    """
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
            f"could not read what changed between [{base}] and [{head}] in "
            f"[{settings.github_repository}]: {error}"
        ) from error

    listed = compared.get(FILES_FIELD, [])

    return SourceDifference(
        base=base,
        head=head,
        files=tuple(_a_changed_file_from(entry) for entry in listed),
        more_files_than_listed=len(listed) >= MOST_FILES_A_COMPARISON_LISTS
    )


def _a_changed_file_from(entry: dict[str, Any]) -> ChangedFile:
    """One entry of the comparison, as this module's own shape.

    The path and the status are required: an entry the API sends without them is
    malformed rather than incomplete, and reading it as a file named `None` would
    put that in front of a model as something it could go and open.
    """
    return ChangedFile(
        path=str(entry[FILENAME_FIELD]),
        status=str(entry[STATUS_FIELD]),
        patch=_text_or_nothing(entry.get(PATCH_FIELD)),
        previous_path=_text_or_nothing(entry.get(PREVIOUS_FILENAME_FIELD))
    )


def _text_or_nothing(value: Any) -> str | None:
    """A field the API may omit, as text or as its absence.

    Checked rather than cast, because the absence is the load-bearing case and
    `str(None)` is the string `"None"` - which would reach a model as a patch
    saying nothing, and as a previous path it could try to read.
    """
    return value if isinstance(value, str) else None


def _headers(settings: RepositorySourceSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_read_token}",
        "Accept": ACCEPT_HEADER
    }
