"""The seam text is turned into vectors through.

Here rather than in either module that uses one. The repository index embeds
passages of source and long-term memory embeds descriptions of incidents; the
two corpora have nothing to do with each other, and what they share is only this
- something that takes a batch and answers in the same order. A type two modules
both name is a contract, and a contract lives in the kernel.

The port alone, and so it installs nothing. The model behind it is
`embedding_fastembed`'s, and a process's root builds it and hands it on.
"""

from __future__ import annotations

from typing import Protocol


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
