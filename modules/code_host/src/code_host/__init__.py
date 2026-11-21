"""The code host, as Argus needs it (spec §12.1, §13).

A port and the one adapter behind it. The port is named for the role - what
Argus asks of whatever hosts the Target Service's repository - and the adapter
for the vendor that answers today, in `code_host.github`. Nothing above the port
sees a route, a token, an archive or a field of a response.

The adapter is not exported here. It is built where a process is wired, and
everything else is handed it typed as a port - so the only modules allowed to
name it are the ones that have to.
"""

from __future__ import annotations

from code_host.failures import (
    BranchNotWritten,
    PullRequestNotOpened,
    RepositoryUnreadable,
)
from code_host.naming import owner_and_name
from code_host.port import (
    ChangedFile,
    CodeHostReads,
    CodeHostWrites,
    Relation,
    SourceDifference,
)

__all__ = [
    "BranchNotWritten",
    "ChangedFile",
    "CodeHostReads",
    "CodeHostWrites",
    "PullRequestNotOpened",
    "Relation",
    "RepositoryUnreadable",
    "SourceDifference",
    "owner_and_name"
]
