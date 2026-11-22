"""The embedder behind the kernel's `Embedder` port: a fastembed model run in
this process.

It runs here. No key, no network, no bill - and those are the reasons it was
chosen, which is worth saying plainly because retrieval quality is not among
them. What it buys instead is that embedding costs nothing, that an incident
never waits on a vendor, and that nothing external has to be stood in for
before a suite can run.

Which model it is, is the caller's to say. The adapter holds no opinion about
which corpus wants which weights, and a benchmark blaming the model needs each
caller free to name a different one. Only a process's root builds one, and
hands it on as the port.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from core.embedding import Embedder

if TYPE_CHECKING:
    from fastembed import TextEmbedding


@lru_cache(maxsize=1)
def _the_model(model_name: str) -> TextEmbedding:
    """The one model this process loads, built on first use.

    Cached because loading it is the expensive part and the weights are the same
    for every text; deferred because a process that only ever injects an embedder
    - which is most of them, and every unit test - should not pay to import an
    ONNX runtime it will not reach.

    Cached on the name, so naming a different model loads that one rather than
    handing back the first model this process happened to load.
    """
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name)


def an_embedder(model_name: str) -> Embedder:
    """The real embedder, as the port everything above is written against.

    The name is required rather than defaulted, because the adapter does not
    know which corpus is being embedded and each has a setting of its own. A
    root reads its own and passes it here.
    """

    def embed(texts: list[str], /) -> list[list[float]]:
        """One vector per text, in the order they were given.

        The order is the contract. What comes back is paired with what went in
        by position and nothing else, so a model that reordered or dropped one
        would hand every text its neighbour's meaning - which is why the pairing
        is zipped strictly where it happens.
        """
        return [vector.tolist() for vector in _the_model(model_name).embed(texts)]

    return embed
