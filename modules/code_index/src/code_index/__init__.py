"""The repository's source, held as something searchable by meaning.

One module owns the index end to end: what a repository is cut into, how a chunk
becomes a vector, where the vectors live, and what comes back when somebody
describes what they are looking for. Reading and writing it are the same
knowledge seen from two sides, and splitting them would put the collection's
name, the model, and the shape of a chunk in two places that have to agree.

What keeps it honest is a watermark rather than a promise: the index records the
commit its chunks describe, and the difference between that and the commit the
repository is at is the whole mechanism - the work list, the retry, and what a
reader is told when what it searched is not what is deployed.
"""

from __future__ import annotations

__all__: list[str] = []
