"""The model that turns passages into vectors.

It runs in this process. No key, no network, no bill - and those are the reasons
it was chosen, which is worth saying plainly because retrieval quality is not
among them. A code-trained hosted model would rank better than a small
general-purpose English one; what this buys instead is that indexing costs
nothing, that an incident never waits on a vendor, and that nothing external has
to be stood in for before a suite can run.

Which is why everything above this is written against a seam. If the benchmark
says retrieval by meaning underperforms, "the model is small" is a hypothesis
that can be tested by passing a different `Embedder` - and only this module has
to know.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from argus_core import get_settings

from code_index.indexing import Embedder

if TYPE_CHECKING:
    from fastembed import TextEmbedding

@lru_cache(maxsize=1)
def _the_model(model_name: str) -> TextEmbedding:
    """The one model this process loads, built on first use.

    Cached because loading it is the expensive part and the weights are the same
    for every passage; deferred because a process that only ever injects an
    embedder - which is most of them, and every unit test - should not pay to
    import an ONNX runtime it will not reach.

    Cached on the name, so naming a different model loads that one rather than
    handing back the first model this process happened to load.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name)


def an_embedder(model_name: str | None = None) -> Embedder:
    """The real embedder, as the seam everything above is written against.

    Named, or the configured model where nothing names one. Which model it is
    is a deployment's choice (`CODE_INDEX_EMBEDDING_MODEL`), because it is the
    one variable the retrieval benchmark cannot hold constant - and the string
    lives in configuration rather than here so that a suite comparing two of
    them has somewhere to say so.

    Read at the call rather than defaulted in the signature: a default argument
    is evaluated at import, which would have this module read the environment to
    be imported at all.
    """
    named = model_name or get_settings().code_index_embedding_model

    def embed(texts: list[str], /) -> list[list[float]]:
        """One vector per text, in the order they were given.

        The order is the contract. What comes back is paired with what went in
        by position and nothing else, so a model that reordered or dropped one
        would hand every passage its neighbour's meaning - which is why the
        pairing is zipped strictly where it happens.
        """
        return [vector.tolist() for vector in _the_model(named).embed(texts)]

    return embed
