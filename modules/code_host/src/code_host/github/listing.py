"""What files a repository holds at a ref, and what one of them says.

The two primitives a model localizes a fault with: between them it can find a
bug in a repository small enough to hold in mind. Each one request - a tree
listed recursively, a file's contents - and each refusing rather than answering
emptily, because a repository that could not be reached, a path that is not
there and a listing the API gave up on are all the same thing to a caller: it
does not know what the code says, and must not proceed as though the code said
nothing.

Which of the files are the service's own is not decided here. That is the
deployment's to say and the read tier's to apply; this answers what the
repository holds.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Final

import httpx2

from code_host.failures import RepositoryUnreadable
from code_host.github.headers import headers_for
from code_host.github.reading import HttpGet
from code_host.github.settings import GitHubReadSettings

logger = logging.getLogger(__name__)

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

# How a tree is asked for whole rather than one directory deep. Without it the
# listing names a directory's files and stops, and a model is told a file one
# level down is not there.
RECURSIVE_PARAMETER: Final = "recursive"
RECURSIVELY: Final = "1"


def list_repository_files(ref: str,
                          settings: GitHubReadSettings,
                          get: HttpGet = httpx2.get) -> list[str]:
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
            headers=headers_for(settings),
            params={RECURSIVE_PARAMETER: RECURSIVELY},
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
        logger.warning("repository listing truncated", extra={"ref": ref})

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
                         settings: GitHubReadSettings,
                         get: HttpGet = httpx2.get) -> str:
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
            headers=headers_for(settings),
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


def _repository(settings: GitHubReadSettings) -> str:
    return f"{settings.github_api_url}/repos/{settings.github_repository}"
