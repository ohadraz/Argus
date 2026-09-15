"""Reading the Target Service's own source (spec §7.4, §12.1, §13).

The read tier's fourth channel, and the one a fault is localized in. Two
primitives: what files there are, and what one of them says. Between them a
model can find a bug in a repository small enough to hold in mind, which is what
the Target Service is - and they are deliberately not enough for a repository
that is not, because deciding what to read when you cannot read everything is a
different problem with a different answer, and the benchmark rather than this
module is where that answer should come from.

Nothing here can write. The credential named in this slice reads a repository
and cannot push to one, so the claim the tier split makes - that this process is
incapable of mutation, not merely disinclined - holds with the repository in it.

Both functions raise rather than answering emptily. A repository that could not
be reached, a path that is not there and a listing the API gave up on are all
the same thing to a caller: it does not know what the code says, and must not
proceed as though the code said nothing.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from typing import Any, Final

import httpx
from argus_core import SettingsSlice

HttpGet = Callable[..., httpx.Response]

REQUEST_TIMEOUT_SECONDS = 10.0

# GitHub's wire vocabulary, named for the fields that carry it. `TRUNCATED_FIELD`
# is the load-bearing one: it is how the API says the answer is incomplete, and
# it arrives beside a perfectly well-formed list of entries.
TREE_FIELD: Final = "tree"
TRUNCATED_FIELD: Final = "truncated"
PATH_FIELD: Final = "path"
ENTRY_TYPE_FIELD: Final = "type"
FILE_ENTRY_TYPE: Final = "blob"
CONTENT_FIELD: Final = "content"
REF_FIELD: Final = "ref"

ACCEPT_HEADER: Final = "application/vnd.github+json"


class RepositoryReadSettings(SettingsSlice):
    """What this tier may know about the repository it reads.

    Names the same repository the write tier does and a different credential,
    and that difference is the boundary rather than a naming preference: this
    one can read source and cannot change it, which is what lets the source be
    read from a process that is incapable of writing anywhere.
    """

    github_api_url: str
    github_repository: str
    github_read_token: str


class RepositoryUnreadable(Exception):
    """The source could not be read, whatever the reason.

    One exception for an unreachable host, a rejected credential, a path that is
    not there, a listing the API truncated and a file that is not text - because
    the caller's next move is the same for all five: it does not know what the
    code says. Every one of them has an innocent-looking empty answer available
    (no files, no content, no matches), and every one of those would be read as
    a fact about the repository rather than about the attempt to read it.
    """


def list_repository_files(ref: str,
                          settings: RepositoryReadSettings,
                          get: HttpGet = httpx.get) -> list[str]:
    """Every file in the repository at `ref`, as paths from its root.

    Directories are left out. The tree answers with both, and a directory is not
    something anybody can read - offering one as a file spends a call to be told
    so, and spends another on the next one.

    Raises `RepositoryUnreadable` when the API truncated its answer. A tree it
    considers too large comes back well-formed, complete-looking and short, with
    the fact that it gave up recorded in a flag beside the entries; a caller that
    missed the flag would conclude that a file it cannot see is a file that does
    not exist.
    """
    url = f"{_repository(settings)}/git/trees/{ref}"

    try:
        response = get(
            url,
            headers=_headers(settings),
            params={"recursive": "1"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not list the files of [{settings.github_repository}] at "
            f"[{ref}]: {error}"
        ) from error

    if answered.get(TRUNCATED_FIELD):
        raise RepositoryUnreadable(
            f"[{settings.github_repository}] at [{ref}] is too large to list: the "
            f"listing came back truncated, so what it does not name cannot be "
            f"taken to be absent"
        )

    return [
        str(entry[PATH_FIELD])
        for entry in answered.get(TREE_FIELD, [])
        if entry.get(ENTRY_TYPE_FIELD) == FILE_ENTRY_TYPE
    ]


def read_repository_file(path: str,
                         ref: str,
                         settings: RepositoryReadSettings,
                         get: HttpGet = httpx.get) -> str:
    """What one file says, at `ref`, as text.

    Raises `RepositoryUnreadable` for a path that is not there rather than
    answering with an empty string: a file that exists and says nothing is a
    real thing a repository holds, and a model handed one for a path that does
    not exist concludes the module is empty and patches a file that is not the
    file.

    Raises for a file that is not text, too. A repository holds images and
    archives beside its source, and decoding one as UTF-8 yields replacement
    characters that reach a model looking like code.
    """
    url = f"{_repository(settings)}/contents/{path}"

    try:
        response = get(
            url,
            headers=_headers(settings),
            params={REF_FIELD: ref},
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        answered: dict[str, Any] = response.json()
        held = base64.b64decode(answered[CONTENT_FIELD])
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not read [{path}] at [{ref}]: {error}"
        ) from error

    return _as_text(held, path)


def _as_text(held: bytes, path: str) -> str:
    """The file's bytes as source, or the failure that they are not source."""
    try:
        return held.decode()
    except (UnicodeDecodeError, binascii.Error) as error:
        raise RepositoryUnreadable(
            f"[{path}] is not text and cannot be read as source: {error}"
        ) from error


def _repository(settings: RepositoryReadSettings) -> str:
    return f"{settings.github_api_url}/repos/{settings.github_repository}"


def _headers(settings: RepositoryReadSettings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_read_token}",
        "Accept": ACCEPT_HEADER
    }
