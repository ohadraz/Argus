"""What an index of the repository is built with.

Everything the stored passages are derived from, apart from the commit: the
model that embedded them, the bounds a file is cut by, and the directories that
are the service. Change any one and the passages are different ones - other
vectors, other cuts, other files - so each recipe is a collection of its own
(`core.embedding.collection_for`) with a mark of its own (`records`). The
commit is the one thing a collection follows rather than is named for.

Spelled once, here, because two processes have to arrive at the same recipe
from the same settings: the catch-up loop that builds a collection and the read
server that searches it.
"""

from __future__ import annotations

from core.source_scope import SCOPE_SEPARATOR, the_prefixes_of


def built_with(*,
               embedding_model: str,
               service_source_paths: str,
               max_lines: int,
               overlap: int) -> str:
    """The recipe these settings build an index with, as one string.

    Readable, because it is what a collection is named for and what its mark
    is filed under, and a person listing either is asking which model and
    which cut.

    The scope as the index reads it (`core.source_scope.the_prefixes_of`),
    sorted, rather than as it was written: the same directories listed in
    another order, or with other spacing, admit the same files, and spelled as
    written they would be another recipe and a whole index built again.
    """
    scope = SCOPE_SEPARATOR.join(sorted(the_prefixes_of(service_source_paths)))

    return f"{embedding_model} lines={max_lines} overlap={overlap} scope={scope}"
