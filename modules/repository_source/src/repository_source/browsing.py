"""Where a deployed revision can be read, as a person opens it.

A deployment platform names the repository it synced from by the address it
clones, which is not the address a reader opens. On GitHub the two are close:
the clone address over HTTPS, less its `.git` - and the commit and the
directory at that commit are pages under it. A host whose pages this does not
know gets no addresses at all, rather than ones that lead nowhere.

The repository is named by owner and name on any host, since that takes no
knowledge of the host's pages.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import RevisionSource

# The one host whose pages are known, and where it serves them.
_GITHUB_HOST: Final = "github.com"
_GITHUB_PAGES: Final = "https://github.com"


def owner_and_name(repo_url: str) -> str:
    """`owner/name` out of a repository's address, over HTTPS or SSH, with or
    without the `.git` a clone address ends in - its last two parts, which is
    the whole of a GitHub repository's name and the end of one nested deeper
    elsewhere."""
    return "/".join(_the_parts_of(repo_url)[-2:])


def where_to_read(repo_url: str, revision: str, path: str | None) -> RevisionSource | None:
    """The repository, the commit and the directory at that commit as their
    pages - or `None` for a repository on a host whose pages are not known."""
    parts = _the_parts_of(repo_url)

    # The host less any user an SSH address logs in as (`git@`), in whichever
    # case it was written: a host name is not case-sensitive.
    if len(parts) < 3 or parts[-3].rpartition("@")[2].lower() != _GITHUB_HOST:
        return None

    repository = owner_and_name(repo_url)
    repository_address = f"{_GITHUB_PAGES}/{repository}"
    directory = path.strip("/") if path else None

    return RevisionSource(
        repository=repository,
        repository_address=repository_address,
        revision_address=f"{repository_address}/commit/{revision}",
        directory=directory or None,
        directory_address=(f"{repository_address}/tree/{revision}/{directory}"
                           if directory else None)
    )


def _the_parts_of(repo_url: str) -> list[str]:
    """The address cut at every separator, the host included: an SSH address
    puts a colon where an HTTPS one puts a slash."""
    address = repo_url.rstrip("/").removesuffix(".git").replace(":", "/")

    return [part for part in address.split("/") if part]
