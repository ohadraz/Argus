"""Which of a repository's files are the service, and which are around it.

A deployment points Argus at a repository and says which directories of it hold
the service. Everything else is scenery - a scenario harness, a deployment
chart, somebody's notebook - and reading it is worse than not reading it: the
demo repository ships the shop beside the rig that stages incidents against it,
and an agent that reads the rig is reading how its own incidents are made.

The rule lives in the kernel because two modules ask it and must agree. The
substring channel skips a file it will not match against, and the index skips
the same file rather than embedding it; the two answering differently would make
what a model can find depend on which tool it happened to reach for.

It takes the setting as the string it is written as, rather than a settings
object. Both callers read the same field, and neither one's slice belongs in a
signature here - a kernel that named a consumer's view of the configuration
would be a kernel that knows who its consumers are.
"""

from __future__ import annotations

SCOPE_SEPARATOR = ","


def belongs_to_the_service(path: str, source_paths: str) -> bool:
    """Whether this path is part of the service, as the deployment says.

    Prefix matching on a comma-separated list, which is what a caller writing
    `src/io_shop,tests/io_shop` in an environment file means by it. Space around
    an entry is not part of it: a list is written with spaces after its commas,
    and a prefix of ` tests/io_shop` matches nothing while failing silently -
    the directory is simply never read and nobody is told why.

    An empty setting admits everything rather than nothing. A deployment that
    scoped nothing has a repository that is all service, and answering it with
    no files at all would report an empty repository - which is a different
    thing from a repository with nothing in scope, and the wrong one.
    """
    scoped = [
        prefix.strip()
        for prefix in source_paths.split(SCOPE_SEPARATOR)
        if prefix.strip()
    ]

    return not scoped or any(path.startswith(prefix) for prefix in scoped)
