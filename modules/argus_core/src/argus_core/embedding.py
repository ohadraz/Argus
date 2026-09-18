"""The model that turns text into vectors, and the seam it is reached through.

Here rather than in either module that uses one. The repository index embeds
passages of source and long-term memory embeds descriptions of incidents; the
two corpora have nothing to do with each other, and what they share is only this
- a local model, loaded once per process, taking a batch and answering in the
same order. A type two modules both name is a contract, and a contract lives in
the kernel.

It runs in this process. No key, no network, no bill - and those are the reasons
it was chosen, which is worth saying plainly because retrieval quality is not
among them. What it buys instead is that embedding costs nothing, that an
incident never waits on a vendor, and that nothing external has to be stood in
for before a suite can run.

Which model it is, is the caller's to say. The kernel holds no opinion about
which corpus wants which weights, and a benchmark blaming the model needs each
caller free to name a different one.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class Embedder(Protocol):
    """What turns text into vectors.

    A seam rather than a call, because the real one loads a model: a unit test
    that reached the default would spend its first second in ONNX and its
    second one deciding what a vector of 384 floats ought to be.

    Takes the whole batch. A single-text signature would make batching the
    caller's problem and, being the easier thing to write, would quietly become
    one call per text.
    """

    def __call__(self, texts: list[str], /) -> list[list[float]]: ...


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
    """The real embedder, as the seam everything above is written against.

    The name is required rather than defaulted, because the kernel does not know
    which corpus is being embedded and each has a setting of its own. A caller
    reads its own and passes it here.
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
