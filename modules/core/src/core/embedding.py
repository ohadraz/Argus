"""The seam text is turned into vectors through.

Here rather than in either module that uses one. The repository index embeds
passages of source and long-term memory embeds descriptions of incidents; the
two corpora have nothing to do with each other, and what they share is only this
- something that takes a batch and answers in the same order. A type two modules
both name is a contract, and a contract lives in the kernel.

The port alone, and so it installs nothing. The model behind it is
`embedding_fastembed`'s, and a process's root builds it and hands it on.

And which collection a corpus embedded by a model is kept in (`collection_for`),
for the same reason: every process that writes a corpus and every one that
searches it has to arrive at the same name.
"""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Final, Protocol

# What a recipe keeps in a collection's name: lower-case letters and digits.
# Everything else - the `/` between an organisation and its model, the `.` in a
# version - becomes a `-`, which is narrower than any store asks.
_NOT_KEPT: Final = re.compile(r"[^a-z0-9]+")

# How much of the recipe's digest a name carries: enough that two recipes whose
# names read alike once made a name are still two collections.
_DIGEST_LENGTH: Final = 8

# How much of the recipe a name spells out. A recipe can be long - the index's
# names every directory of the service - and a store refuses a long name; the
# digest, taken over the whole recipe, is what keeps the name exact.
_READABLE_LENGTH: Final = 64


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


def collection_for(corpus: str, built_with: str) -> str:
    """The collection `corpus` is kept in, as built with `built_with`: the
    embedding model, and whatever else the corpus's points are derived from.

    A vector means something only beside vectors the same model made, so the
    model is part of the name. A collection named for the corpus alone holds
    whatever any model ever wrote into it: a model of the same width mixes its
    vectors with the last one's, and a query is answered from both, wrongly and
    without an error. Named this way, changing what a corpus is built with
    starts a collection of its own, and a reader embeds its question with the
    model that wrote the collection it searches, because it named the
    collection by that model.

    What it was built with made readable and cut short, then its digest, which
    is what keeps two recipes apart whose names read alike once made readable.
    """
    readable = _NOT_KEPT.sub("-", built_with.lower())[:_READABLE_LENGTH].strip("-")
    digest = sha256(built_with.encode()).hexdigest()[:_DIGEST_LENGTH]

    return f"{corpus}__{readable}_{digest}"
