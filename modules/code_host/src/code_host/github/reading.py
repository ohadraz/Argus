"""Reading a repository's whole source, at a commit.

One request and one answer: every readable file at a ref, as a path and what it
says. Two modules ask it - the substring channel matches lines against it, and
the index cuts it into passages - and neither has any business knowing that
GitHub serves a repository as a tarball wrapped in a directory named after the
commit.

Whole rather than per file, because forty reads to answer one question is forty
chances to be rate-limited and forty round trips somebody waits through. That
works because the Target Service is small, which is the assumption the substring
channel already rests on - and the one the index exists to lift.

A pure rule about which paths are the service's own is a line and belongs in
`core`; this is tarfile handling and a vendor's API, which is this adapter's.
"""

from __future__ import annotations

import binascii
import io
import tarfile
from collections.abc import Callable
from typing import Final

import httpx2

from code_host.failures import RepositoryUnreadable
from code_host.github.headers import headers_for
from code_host.github.settings import GitHubReadSettings

HttpGet = Callable[..., httpx2.Response]

# Longer than an ordinary API call's budget. This one transfers a repository
# rather than a JSON document, and the wait is paid once for the whole of it
# instead of once per file.
ARCHIVE_TIMEOUT_SECONDS: Final = 30.0


def the_source_at(ref: str,
                  settings: GitHubReadSettings,
                  get: HttpGet = httpx2.get) -> dict[str, str]:
    """Every readable file at `ref`, keyed by its path from the repository root.

    Files that are not text are skipped rather than refused. A repository's
    images are simply not where a matching line or an indexable passage can be,
    and refusing the whole read over one of them would make search impossible in
    any repository holding a logo.

    Raises `RepositoryUnreadable` rather than answering emptily. "The repository
    has no files" and "I could not read the repository" are opposite things and
    must not arrive looking alike.
    """
    url = f"{settings.github_api_url}/repos/{settings.github_repository}/tarball/{ref}"

    try:
        response = get(
            url,
            headers=headers_for(settings),
            timeout=ARCHIVE_TIMEOUT_SECONDS,
            follow_redirects=True
        )
        response.raise_for_status()

        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:*") as archive:
            return {
                path: source
                for member in archive.getmembers()
                if member.isfile()
                for path in [_without_the_archives_own_directory(member.name)]
                for source in [_the_text_in(archive, member)]
                if source is not None
            }
    except Exception as error:
        raise RepositoryUnreadable(
            f"could not read the source of [{settings.github_repository}] at "
            f"[{ref}]: {error}"
        ) from error


def _without_the_archives_own_directory(name: str) -> str:
    """The path as the repository holds it.

    GitHub wraps an archive in a directory named for the owner, the repository
    and the commit it was cut at - so every entry arrives prefixed with
    something no caller asked about and no other tool here accepts.
    """
    _, _, path = name.partition("/")

    return path or name


def _the_text_in(archive: tarfile.TarFile, member: tarfile.TarInfo) -> str | None:
    """What one entry says, or `None` where it does not say anything readable."""
    held = archive.extractfile(member)

    if held is None:
        return None

    try:
        return held.read().decode()
    except (UnicodeDecodeError, binascii.Error):
        return None
