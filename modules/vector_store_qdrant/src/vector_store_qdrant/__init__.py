"""The vector store's one adapter, named for the vendor that answers today.

Two modules, split where the ports are split. `searching` answers
`VectorSearch` and is the only part of this package the worker's root may build;
`indexing` answers `VectorIndex` and is built only by the processes that fill a
corpus. The layering guard holds the split: recall's read is the one way a walk
reaches the vendor's client, and the writing side is a module no walk may import.

Only the reading side is exported here. The writing side is imported by module
path, by the two roots that build it (`apps.deliverer`, `apps.indexer`), so
naming this package never reaches it.
"""

from __future__ import annotations

from vector_store_qdrant.searching import QdrantSearch, SearchOpenedOnFirstUse, the_search_at

__all__ = [
    "QdrantSearch",
    "SearchOpenedOnFirstUse",
    "the_search_at"
]
