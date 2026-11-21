"""Reading the Target Service's own source (spec §7.4, §12.1, §13).

The read tier's fourth channel, and the one a fault is localized in: what files
there are, what one of them says, and every line matching a substring. The
second is the code host's answer as it stands, asked by `server`; the other two
are scoped here. Between them a model can find a bug in a repository small
enough to hold in mind, which is what the Target Service is - and they are
deliberately not enough for a repository that is not, because deciding what to
read when you cannot read everything is a different problem with a different
answer, and the benchmark rather than this module is where that answer should
come from.

Nothing here can write. The code host this tier is handed is typed as its reads
port and holds a credential that reads a repository and cannot push to one, so
the claim the tier split makes - that this process is incapable of mutation, not
merely disinclined - holds with the repository in it.

What is this module's own is which files are the service's: the repository
answers what it holds, and the deployment says which of it is the thing being
fixed. Every read raises rather than answering emptily, as the port does: a
repository that could not be reached is not one that holds nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from code_host import CodeHostReads
from core import SettingsSlice
from core.models import CodeOutsideThePatch
from core.source_scope import belongs_to_the_service

from read_mcp_server.outside_the_patch import code_outside_the_patch

# How many matching lines one search may answer with. A ceiling rather than a
# budget: a query like `def` matches a repository entire, and the answer would
# then be the repository - which is the thing search exists to avoid sending.
# Reaching it is said in the answer, because a model that does not know its
# answer was cut short will read it as the whole truth.
MOST_HITS_WORTH_ANSWERING: Final = 100


class RepositoryReadSettings(SettingsSlice):
    """What this tier may know about the repository it reads, beyond where it is.

    Where it is and the credential that reads it are the code host's adapter's,
    built in `server`; what is left is which of it is the service.
    """

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


def list_repository_files(ref: str,
                          settings: RepositoryReadSettings,
                          *,
                          code: CodeHostReads) -> list[str]:
    """Every file of the service in the repository at `ref`, as paths from its
    root.

    Raises `RepositoryUnreadable` where the repository could not be listed in
    full - the host truncating its own answer included: a listing missing files
    reads as a repository without them.
    """
    return [path for path in code.files_at(ref) if _is_the_service_s_own(path, settings)]


def search_repository(query: str,
                      ref: str,
                      settings: RepositoryReadSettings,
                      *,
                      code: CodeHostReads) -> list[str]:
    """Every line in the repository at `ref` containing `query`.

    The channel that turns a named cause into a place to look. Code-Fix is
    handed what the investigation concluded - a flag name, a function, a
    message from a log line - and listing alone leaves it opening files by
    guessing at their names. It does that badly, and it runs out of turns doing
    it: a repository of forty files is forty guesses and a dozen turns.

    One read of the whole source, not one per file, because forty reads to
    answer one question is forty chances to be rate-limited and forty
    round-trips a model waits through. It works because the Target Service is
    small, which is the same assumption the rest of this module rests on and the
    same one the RAG retriever exists to lift.

    Answers as a developer's own tool would - `path:line: text` - so a hit says
    whether the file is worth opening without opening it, by the path the read
    of one file takes.

    Substring, not regular expression. What arrives is whatever a model wrote,
    and a pattern that fails to compile is an error about the query rather than
    an answer about the code - where a substring that matches nothing is a fact
    about the repository, and a useful one.

    Raises `RepositoryUnreadable` when the source could not be fetched. No
    matches and could-not-look are the same empty list to a caller and opposite
    facts about the world, and the silent one teaches a model that the cause is
    not in the code.
    """
    held = code.source_at(ref)
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


def read_code_outside_the_patch(
    patch: dict[str, str],
    ref: str,
    settings: RepositoryReadSettings,
    *,
    code: CodeHostReads,
    analyse: Callable[[dict[str, str], dict[str, str]], CodeOutsideThePatch] = (
        code_outside_the_patch
    )
) -> CodeOutsideThePatch:
    """How the service's own code at `ref` uses what `patch` changes, and every
    name that code defines outside the patch's files.

    One read of the source, as a search reads it and scoped as a search is
    scoped: the rig that stages incidents is not where the patch's readers live.
    What each line does is the syntax tree's to say, in `outside_the_patch`.

    Raises `RepositoryUnreadable` when the source could not be fetched. No uses
    because none exist and no uses because nothing was read are opposite facts,
    and the silent one says nothing outside the patch depends on what it changed.
    """
    held = code.source_at(ref)

    return analyse(
        {path: source for path, source in held.items()
         if _is_the_service_s_own(path, settings)},
        patch
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
