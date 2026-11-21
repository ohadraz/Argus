"""The code host, as GitHub answers for it.

The only place in Argus that knows GitHub's API: its routes, its media type,
how a credential is sent, that a repository comes as a tarball wrapped in a
directory named for the commit, that a listing says it gave up in a flag beside
its entries, that a comparison stops at three hundred files without saying so,
how a commit is built from a tree, and that a pull request is opened as a draft.
Everything above the port asks for what it wants and gets Argus's own values
back.

Built only where a process is wired - each server's `server.py` and the index's
`catching_up` - and handed on typed as a port.
"""

from __future__ import annotations

from code_host.github.hosting import GitHub, GitHubReads
from code_host.github.settings import GitHubReadSettings, GitHubSettings

__all__ = [
    "GitHub",
    "GitHubReadSettings",
    "GitHubReads",
    "GitHubSettings"
]
