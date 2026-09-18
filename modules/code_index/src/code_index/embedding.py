"""Which model the repository index embeds its passages with.

The model itself is the kernel's (`argus_core.embedding`), because long-term
memory embeds with one too and a thing two modules both name is a contract.
What is left here is the only part that belongs to this index: which weights it
asks for.

Configuration rather than a constant, because it is the one variable a
retrieval benchmark (§21) cannot hold constant - if the benchmark says retrieval
by meaning underperforms, "the model is small" is a hypothesis that can be
tested by naming a different one, and only this line has to change.
"""

from __future__ import annotations

from argus_core import get_settings
from argus_core.embedding import Embedder
from argus_core.embedding import an_embedder as a_model_named


def an_embedder(model_name: str | None = None) -> Embedder:
    """The embedder this index uses: the one named, or the one configured.

    Read at the call rather than defaulted in the signature: a default argument
    is evaluated at import, which would have this module read the environment to
    be imported at all.
    """
    return a_model_named(model_name or get_settings().code_index_embedding_model)
