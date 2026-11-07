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

import re
from dataclasses import dataclass
from typing import Any, Final

import httpx2

from repository_source.comparing import (
    BEHIND,
    BETWEEN,
    DIVERGED,
    FILENAME_FIELD,
    FILES_FIELD,
    MERGE_BASE_FIELD,
    MOST_FILES_A_COMPARISON_LISTS,
    PREVIOUS_FILENAME_FIELD,
    RELATION_FIELD,
    SHA_FIELD,
)
from repository_source.headers import headers_for
from repository_source.reading import (
    HttpGet,
    RepositorySourceSettings,
    RepositoryUnreadable,
)

# The two fields of a comparison entry that `comparing.py` has no use for. The
# status is how the API says whether the file arrived, left, moved or merely
# changed; the patch is the change itself, and is the reason this module exists.
STATUS_FIELD: Final = "status"
PATCH_FIELD: Final = "patch"

# The statuses a file is turned round between, read in the other direction: a
# file one side added the other removed, one it renamed the other renamed back,
# and one it copied the other removed. Every other status reads the same either
# way.
ADDED_FILE: Final = "added"
REMOVED_FILE: Final = "removed"
RENAMED_FILE: Final = "renamed"
COPIED_FILE: Final = "copied"

# How a patch says what it is a patch of: a hunk's header, its lines out and
# in, and git's note that a line ends without one - which belongs to the line
# before it.
_A_HUNK_HEADER: Final = re.compile(r"@@ -(\S+) \+(\S+) @@(.*)")
_A_LINE_TAKEN_OUT: Final = "-"
_A_LINE_PUT_IN: Final = "+"
_NO_NEWLINE: Final = "\\"

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

    `status` is carried as the API spelled it, and turned round only where the
    file is read in the other direction (`taken_away`). A vocabulary of this
    module's own would be a second spelling for a reader to learn for no gain.
    """

    path: str
    status: str
    patch: str | None = None
    previous_path: str | None = None
    # Where a copy the other side made was copied from, on the file the deploy
    # removed for not having it - which carries no patch, since the comparison
    # shows only how the copy differed from its source. Set there alone.
    copied_from: str | None = None


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

    `relation` is how `head` stands to `base`, in GitHub's word for it, and
    `merge_base` where their lines of history part. `files` is what `head`
    changed since then - which, for a head not ahead of its base, is not all
    of what differs: `taken_away` is what `base` had changed since then and
    `head` does not have, each read as going from `base` to `head`, so every
    patch in the difference reads in one direction. Empty where `head` is
    ahead, since it then has all of it.
    """

    base: str
    head: str
    files: tuple[ChangedFile, ...]
    more_files_than_listed: bool
    relation: str | None = None
    merge_base: str | None = None
    taken_away: tuple[ChangedFile, ...] = ()


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

    Where `head` is not ahead of `base` - a deploy back to an earlier revision,
    or from a branch cut before the one that ran - asked the other way round as
    well. GitHub lists what the head changed since the two lines parted, and a
    deploy back to an ancestor changed nothing since then: listed alone, it read
    as a deploy that changed no file at all, which rules it out as a cause.
    """
    compared = _compared(base, head, settings, get)
    listed = compared.get(FILES_FIELD, [])
    relation = compared.get(RELATION_FIELD)
    away = (_compared(head, base, settings, get).get(FILES_FIELD, [])
            if relation in (BEHIND, DIVERGED) else [])

    return SourceDifference(
        base=base,
        head=head,
        files=tuple(_a_changed_file_from(entry) for entry in listed),
        more_files_than_listed=any(len(side) >= MOST_FILES_A_COMPARISON_LISTS
                                   for side in (listed, away)),
        relation=relation if isinstance(relation, str) else None,
        merge_base=_text_or_nothing((compared.get(MERGE_BASE_FIELD) or {}).get(SHA_FIELD)),
        taken_away=tuple(_as_the_deploy_did_it(_a_changed_file_from(entry)) for entry in away)
    )


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
            url, headers=headers_for(settings), timeout=COMPARISON_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        compared: dict[str, Any] = response.json()
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not read what changed between [{base}] and [{head}] in "
            f"[{settings.github_repository}]: {error}"
        ) from error

    return compared


def _as_the_deploy_did_it(changed: ChangedFile) -> ChangedFile:
    """A file the base's side changed, read the other way round: as the
    deploy that does not have that change did it to the file.

    Added becomes removed and removed added, a rename goes back to where it
    came from, and the patch is put the other way round - so a port the base's
    side moved reads as the port the deploy put back, never as one it moved.

    A copy is removed, with no patch: its patch is how the copy differed from
    its source, which turned round is not what removing it took out.
    """
    if changed.status == COPIED_FILE:
        return ChangedFile(path=changed.path, status=REMOVED_FILE,
                           copied_from=changed.previous_path)

    renamed = changed.status == RENAMED_FILE and changed.previous_path is not None

    return ChangedFile(
        path=changed.previous_path if renamed and changed.previous_path else changed.path,
        status={ADDED_FILE: REMOVED_FILE, REMOVED_FILE: ADDED_FILE}.get(changed.status,
                                                                         changed.status),
        patch=_the_other_way_round(changed.patch) if changed.patch is not None else None,
        previous_path=changed.path if renamed else changed.previous_path
    )


def _the_other_way_round(patch: str) -> str:
    """A patch read in the other direction, as git writes one.

    Each hunk's two ranges change places, and in every run of changes the
    lines put in become the lines taken out and set first, as git sets what a
    change takes out before what it puts in. A "no newline" note stays with
    the line it is about.
    """
    said: list[str] = []
    taken_out: list[list[str]] = []
    put_in: list[list[str]] = []
    last: list[str] | None = None

    for line in patch.split("\n"):
        if line.startswith(_NO_NEWLINE) and last is not None:
            last.append(line)
            continue

        if line.startswith(_A_LINE_TAKEN_OUT):
            last = [f"{_A_LINE_PUT_IN}{line[1:]}"]
            put_in.append(last)
            continue

        if line.startswith(_A_LINE_PUT_IN):
            last = [f"{_A_LINE_TAKEN_OUT}{line[1:]}"]
            taken_out.append(last)
            continue

        said.extend(each for change in (*taken_out, *put_in) for each in change)
        taken_out, put_in, last = [], [], None
        header = _A_HUNK_HEADER.fullmatch(line)
        said.append(f"@@ -{header[2]} +{header[1]} @@{header[3]}" if header else line)

    said.extend(each for change in (*taken_out, *put_in) for each in change)

    return "\n".join(said)


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
