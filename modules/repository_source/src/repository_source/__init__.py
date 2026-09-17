"""A repository's source, read whole at a commit.

What two modules would otherwise each know about GitHub: that a repository comes
as a tarball, that the tarball is wrapped in a directory named for the commit,
and that an entry which is not text is to be passed over rather than refused.

The substring channel matches lines against what this answers; the index cuts it
into passages. Neither should have to know any of the above, and two copies of
it would be two chances to disagree about what a path is called.
"""

from __future__ import annotations

from repository_source.comparing import paths_changed_between
from repository_source.heads import the_head_of
from repository_source.reading import (
    RepositorySourceSettings,
    RepositoryUnreadable,
    the_source_at,
)

__all__ = [
    "RepositorySourceSettings",
    "RepositoryUnreadable",
    "paths_changed_between",
    "the_head_of",
    "the_source_at",
]
