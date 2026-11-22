"""Which model the repository index embeds its passages with.

The model itself is the kernel's (`core.embedding`), because long-term
memory embeds with one too and a thing two modules both name is a contract.
What is left here is the only part that belongs to this index: the embedder it
asks for, by the name its deployment configures.

Configuration rather than a constant, because it is the one variable a
retrieval benchmark (§21) cannot hold constant - if the benchmark says retrieval
by meaning underperforms, "the model is small" is a hypothesis that can be
tested by naming a different one, and only that setting has to change.
"""

from __future__ import annotations

from core.embedding import Embedder
from core.embedding import an_embedder as a_model_named


def an_embedder(model_name: str) -> Embedder:
    """The embedder this index uses: the one its deployment names.

    Named by the caller, never read here: the indexer and the read tier both
    embed with it, and each process's root reads which one from its settings
    (`repository_index_embedding_model`) - a passage and the question asked of
    it are comparable only under one model.
    """
    return a_model_named(model_name)
