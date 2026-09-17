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
from typing import Any, Final, Protocol

import httpx
from argus_core import SettingsSlice
from argus_core.source_scope import belongs_to_the_service
from repository_source import RepositorySourceSettings, the_source_at

# Re-exported under its own name rather than merely imported. This module raises
# it for failures of its own - a path that is not there, a listing the API
# truncated - so it is part of what this module offers, and mypy is right to
# want that said out loud instead of inferred from an import.
from repository_source import RepositoryUnreadable as RepositoryUnreadable

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

# How long a whole repository may take to arrive. Longer than a single file's
# read, because it is a whole repository - and still short, because a model is
# waiting on it and an incident is open.
ARCHIVE_TIMEOUT_SECONDS: Final = 30.0

# How many matching lines one search may answer with. A ceiling rather than a
# budget: a query like `def` matches a repository entire, and the answer would
# then be the repository - which is the thing search exists to avoid sending.
# Reaching it is said in the answer, because a model that does not know its
# answer was cut short will read it as the whole truth.
MOST_HITS_WORTH_ANSWERING: Final = 100


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
    # Which directories of that repository hold the service itself, as a
    # comma-separated list of path prefixes. Empty means the whole repository,
    # which is right whenever the repository is nothing but the service.
    #
    # A repository often holds more than the thing being fixed - the rig that
    # stages faults against it, generated fixtures, deployment scaffolding - and
    # an agent reading those is reading about its own incidents rather than
    # about the code that caused one. Configuration rather than a rule, because
    # where a service's source lives is a fact about a deployment and not
    # something this module could know.
    github_source_paths: str = ""


# The failure this module raises is the one the reader raises, rather than a
# second class meaning the same thing. A caller that had to catch two would
# eventually catch one - and which one it missed would depend on whether the
# source happened to arrive as an archive or as a single file, which is exactly
# the distinction a caller has no business knowing about.
#
# What it covers here is wider than what the reader raises it for: a path that
# is not there and a listing the API truncated are this module's own, and belong
# under it for the reason the rest do. The caller's next move is the same for
# all of them - it does not know what the code says, and every one of them has
# an innocent-looking empty answer available that would be read as a fact about
# the repository rather than about the attempt to read it.


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
        path
        for entry in answered.get(TREE_FIELD, [])
        if entry.get(ENTRY_TYPE_FIELD) == FILE_ENTRY_TYPE
        for path in [str(entry[PATH_FIELD])]
        if _is_the_service_s_own(path, settings)
    ]


class SourceReader(Protocol):
    """How this module gets hold of a repository's source.

    The seam is the reader rather than the HTTP call underneath it. Fetching an
    archive and unwrapping it belongs to `repository_source` and is tested
    there; what belongs here is what this module does with the files once it has
    them - match lines, apply the scope, say where a hit is. A test that handed
    over a real tarball to exercise those three would be re-testing somebody
    else's unpacking to reach its own subject.
    """

    def __call__(self,
                 ref: str,
                 settings: RepositorySourceSettings,
                 /) -> dict[str, str]: ...


def search_repository(query: str,
                      ref: str,
                      settings: RepositoryReadSettings,
                      read_source: SourceReader = the_source_at) -> list[str]:
    """Every line in the repository at `ref` containing `query`.

    The channel that turns a named cause into a place to look. Code-Fix is
    handed what the investigation concluded - a flag name, a function, a
    message from a log line - and listing alone leaves it opening files by
    guessing at their names. It does that badly, and it runs out of turns doing
    it: a repository of forty files is forty guesses and a dozen turns.

    One request, not one per file. The whole repository arrives as an archive
    and is matched here, because forty reads to answer one question is forty
    chances to be rate-limited and forty round-trips a model waits through. It
    works because the Target Service is small, which is the same assumption the
    rest of this module rests on and the same one the RAG retriever behind this
    seam exists to lift.

    Answers as a developer's own tool would - `path:line: text` - so a hit says
    whether the file is worth opening without opening it. Paths are the ones
    `read_repository_file` takes: the archive names every entry under a
    directory of its own, and a hit reported with that prefix would send the
    model to a file that does not exist.

    Substring, not regular expression. What arrives is whatever a model wrote,
    and a pattern that fails to compile is an error about the query rather than
    an answer about the code - where a substring that matches nothing is a fact
    about the repository, and a useful one.

    Raises `RepositoryUnreadable` when the source could not be fetched. No
    matches and could-not-look are the same empty list to a caller and opposite
    facts about the world, and the silent one teaches a model that the cause is
    not in the code.
    """
    held = read_source(ref, _the_source_settings(settings))
    hits: list[str] = []

    for path, source in held.items():
        if not _is_the_service_s_own(path, settings):
            continue

        for number, line in enumerate(source.splitlines(), start=1):
            if query not in line:
                continue

            if len(hits) == MOST_HITS_WORTH_ANSWERING:
                hits.append(
                    f"... and more, not listed: [{query}] matches more than "
                    f"{MOST_HITS_WORTH_ANSWERING} lines. Search for something "
                    f"narrower."
                )

                return hits

            hits.append(f"{path}:{number}: {line.strip()}")

    return hits


def _the_source_settings(
    settings: RepositoryReadSettings
) -> RepositorySourceSettings:
    """This tier's view of the repository, as the reader asks for it.

    A slice of a slice. The reader needs the repository and a credential and
    has no use for the source paths, which are this module's business and the
    index's separately.
    """
    return RepositorySourceSettings(
        github_api_url=settings.github_api_url,
        github_repository=settings.github_repository,
        github_read_token=settings.github_read_token
    )


def _is_the_service_s_own(path: str, settings: RepositoryReadSettings) -> bool:
    """Whether this path is part of the service, as the deployment says.

    The rule itself is the kernel's, because the index asks it too and the two
    must agree: a file this channel will not match against and a file the index
    will not embed have to be the same file, or what a model can find depends on
    which tool it reached for. What stays here is only the reading of this
    module's own settings slice.
    """
    return belongs_to_the_service(path, settings.github_source_paths)




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
